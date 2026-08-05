"""LLM node, loop, max 2 correction attempts (ARCHITECTURE.md Sec3.5).

Checks: correct/plausible use of supporting docs, traceability accuracy,
steps-vs-expected-results count parity, correct set/wait/verify usage,
step-vocabulary conformance to config/step_grammar.yaml, and the
Test_Start/End_of_Test bracketing rule. Cheap structural checks run in pure
Python first (cost-optimization split, ARCHITECTURE.md Sec11); only the
semantic checks (supporting-doc plausibility, traceability accuracy) need the
LLM. If a test case still fails after 2 correction attempts: keep it, set
needs_review=True. Never drop, never halt the run.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, Field

from config_loader import RunConfig
from llm import is_mock
from logging_setup import get_logger, log_data, stage
from schemas import SupportingDocUsagePlan, TestCase, VerificationResult
from subagents.draft_utils import TestCaseDraft, normalize_and_finalize, test_case_to_draft

log = get_logger("verification_correction_agent")

MAX_ATTEMPTS = 2

SYSTEM_PROMPT = """You are verifying one generated HIL qualification test case. Check:
- Traceability accuracy: does the test case content actually relate to its listed \
requirement IDs?
- Plausible/correct use of any referenced supporting-doc signals or parameters.
- Steps-vs-expected-results count parity (equal or nearly equal).
If something is wrong, return passed=false with specific issues AND a corrected \
version of the test case (same structure). If it's fine, return passed=true with an \
empty issues list and no corrected test case."""


class _VerificationAndCorrection(BaseModel):
    result: VerificationResult
    corrected_test_case: TestCaseDraft | None = None


def _pure_python_checks(test_case: TestCase, step_grammar: dict) -> list[str]:
    issues: list[str] = []

    bracket = step_grammar.get("bracket_keywords", {})
    start_kw = bracket.get("start", "Test_Start")
    end_kw = bracket.get("end", "End_of_Test")
    if test_case.steps[0].keyword != start_kw or test_case.steps[-1].keyword != end_kw:
        issues.append(f"step bracketing violated (expected first={start_kw!r} last={end_kw!r})")

    patterns: list[tuple[str, str]] = []
    for entry in step_grammar.get("primitive_keywords", []):
        patterns.append((entry["name"], entry["pattern"]))
    for entry in step_grammar.get("extended_keywords", []):
        patterns.append((entry["name"], entry["pattern"]))

    for step in test_case.steps[1:-1]:  # bracket steps are exempt from grammar patterns
        if not any(re.match(p, step.raw_text) for _, p in patterns):
            issues.append(f"step {step.step_no} ('{step.raw_text}') does not match any configured step-grammar pattern")

    for step in test_case.steps:
        if step.keyword == "set" and "==" not in step.raw_text and "=" not in step.raw_text:
            issues.append(f"step {step.step_no}: 'set' step missing '=' assignment")
        if step.keyword == "verify" and "==" not in step.raw_text:
            issues.append(f"step {step.step_no}: 'verify' step missing '==' comparison")

    non_bracket_steps = len(test_case.steps) - 2
    expected_count = len(test_case.expected_results)
    if expected_count and abs(non_bracket_steps - expected_count) > 2:
        issues.append(
            f"step count ({non_bracket_steps}) not close to expected-results count ({expected_count})"
        )

    return issues


def _mock_semantic_check() -> VerificationResult:
    return VerificationResult(passed=True, issues=[], correction_attempt=0)


def _verify_one(
    llm,
    test_case: TestCase,
    config: RunConfig,
    usage_plans_by_req: dict[str, SupportingDocUsagePlan],
) -> TestCase:
    attempt = 0
    current = test_case

    while True:
        structural_issues = _pure_python_checks(current, config.step_grammar)

        if is_mock(llm):
            semantic = _mock_semantic_check()
        elif attempt == 0 and not structural_issues:
            # still run the LLM semantic check even when structure is clean
            structured = llm.with_structured_output(_VerificationAndCorrection)
            relevant = [usage_plans_by_req[r] for r in current.traceability if r in usage_plans_by_req]
            prompt = f"{SYSTEM_PROMPT}\n\nTest case:\n{current.model_dump_json(indent=2)}\n\nSupporting-doc usage plans:\n{relevant}"
            result = structured.invoke(prompt)
            semantic = result.result
            if not semantic.passed and result.corrected_test_case is not None:
                current, _ = normalize_and_finalize(result.corrected_test_case, current.id, current.traceability)
        else:
            semantic = VerificationResult(passed=not structural_issues, issues=structural_issues)

        all_issues = structural_issues + [i for i in semantic.issues if i not in structural_issues]
        passed = not all_issues

        if passed:
            log.info("  %s: PASSED (attempt %d)", current.id, attempt)
            return current

        log.warning("  %s: FAILED verification (attempt %d): %s", current.id, attempt, all_issues)

        if attempt >= MAX_ATTEMPTS:
            log.warning("  %s: exceeded %d correction attempts -- keeping test case with needs_review=True", current.id, MAX_ATTEMPTS)
            current = current.model_copy(update={"needs_review": True})
            return current

        attempt += 1
        if is_mock(llm):
            # deterministic mock has nothing to correct against; just retry the loop
            # with the same content once, then fall through to needs_review.
            continue

        structured = llm.with_structured_output(_VerificationAndCorrection)
        prompt = (
            f"{SYSTEM_PROMPT}\n\nThe following test case failed verification with issues: {all_issues}\n"
            f"Fix it.\n\nTest case:\n{current.model_dump_json(indent=2)}"
        )
        result = structured.invoke(prompt)
        if result.corrected_test_case is not None:
            current, _ = normalize_and_finalize(result.corrected_test_case, current.id, current.traceability)


def run(
    llm,
    config: RunConfig,
    test_cases: list[TestCase],
    usage_plans: list[SupportingDocUsagePlan],
) -> list[TestCase]:
    with stage(log, "verification_correction_agent", test_cases=len(test_cases)):
        usage_plans_by_req = {p.requirement_id: p for p in usage_plans}
        verified = [_verify_one(llm, tc, config, usage_plans_by_req) for tc in test_cases]

        needs_review = [tc.id for tc in verified if tc.needs_review]
        if needs_review:
            log.warning("  %d test case(s) kept with needs_review=True: %s", len(needs_review), needs_review)
        log_data(log, "verified_test_cases", verified)
        return verified
