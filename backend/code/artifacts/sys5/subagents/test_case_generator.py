"""LLM node, domain-aware: one cluster -> TestCase[] (ARCHITECTURE.md Sec3.4).

Generates multiple test cases per cluster when multiple behavior
patterns/variations exist, aiming to collectively cover functionality check,
stress test, boundary value check, invalid values check and load test where
applicable to that cluster's testable behavior -- without tagging any single
test case with that category in its output content (user instruction; see
ARCHITECTURE.md Sec8 Q12/Q13 for the open conflict with the reference
workbook's Item_List "Test type" column).

Every test case is bracketed Test_Start ... End_of_Test (hard rule). Raw LLM
output is parsed into a permissive draft (subagents.draft_utils), then
normalized (pure Python) to guarantee that bracketing before the strict
TestCase model is constructed -- cheaper and more reliable than relying on
the verification/correction loop to catch a structural rule that can just be
enforced deterministically.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from config_loader import RunConfig
from llm import is_mock
from logging_setup import get_logger, log_data, stage
from schemas import ItemListEntry, RequirementCluster, RequirementRow, TestCase, TestPatternFactor, TestPatternRow
from subagents.draft_utils import TestCaseDraft, TestStepDraft, make_id, normalize_and_finalize

log = get_logger("test_case_generator")

TEST_TYPES = ["functionality_check", "stress_test", "boundary_value_check", "invalid_values_check", "load_test"]

SYSTEM_PROMPT = """You generate HIL-executable SYS5 qualification test cases for one \
cluster of requirements. Rules:
- Every test case's step list starts with Test_Start (step 1) and ends with \
End_of_Test (last step) -- no exceptions.
- Steps use keyword `set` for assignment (single '='), `wait` for a pause/condition, \
`verify` for a comparison in expected results (double '=='). Additional keywords may \
be used if the domain requires a named macro or library call.
- Split steps across phases: precondition, action, postcondition.
- Number of test steps should be equal to or nearly equal to the number of expected- \
result rows.
- Across the test cases you generate for this cluster, collectively cover whichever \
of these apply to the cluster's testable behavior: functionality check, stress test, \
boundary value check, invalid values check, load test. Do NOT name or label which \
category a test case belongs to anywhere in its content -- coverage must be evident \
from the situations/ranges/values you choose, not from an explicit tag.
"""


class _GenerationBatch(BaseModel):
    test_cases: list[TestCaseDraft] = Field(default_factory=list)
    test_pattern_factors: list[TestPatternFactor] = Field(default_factory=list)
    test_pattern_rows: list[TestPatternRow] = Field(default_factory=list)


def _mock_generate(cluster: RequirementCluster, requirements_by_id: dict[str, RequirementRow]) -> _GenerationBatch:
    reqs = [requirements_by_id[r] for r in cluster.requirement_ids if r in requirements_by_id]
    feature = (reqs[0].columns.get("Feature") or reqs[0].source_sheet) if reqs else cluster.cluster_id
    signal = "MOCK_SIGNAL"

    def steps_for(value: str) -> list[TestStepDraft]:
        return [
            TestStepDraft(phase="precondition", keyword="Test_Start", raw_text="Test_Start"),
            TestStepDraft(phase="precondition", keyword="set", raw_text=f"set {signal} = {value}", parameters={signal: value}),
            TestStepDraft(phase="action", keyword="wait", raw_text="wait 100", parameters={"duration": "100"}, parameter_units="ms"),
            TestStepDraft(phase="action", keyword="verify", raw_text=f"verify {signal} == {value}", expected_value=value),
            TestStepDraft(phase="postcondition", keyword="End_of_Test", raw_text="End_of_Test"),
        ]

    drafts = [
        TestCaseDraft(
            feature=feature, objective=f"[MOCK] verify nominal behavior for {cluster.cluster_id}",
            description=f"[MOCK] functionality check covering {cluster.cluster_id} under nominal input.",
            steps=steps_for("50"),
            expected_results=[f"{signal} reads 50"],
            internal_test_type="functionality_check",
        ),
        TestCaseDraft(
            feature=feature, objective=f"[MOCK] verify boundary behavior for {cluster.cluster_id}",
            description=f"[MOCK] boundary value check covering {cluster.cluster_id} at the upper input limit.",
            steps=steps_for("100"),
            expected_results=[f"{signal} reads 100"],
            internal_test_type="boundary_value_check",
        ),
    ]
    return _GenerationBatch(test_cases=drafts)


def run(
    llm,
    config: RunConfig,
    cluster: RequirementCluster,
    requirements_by_id: dict[str, RequirementRow],
    domain_prompt_text: str,
    sequence_start: int,
) -> tuple[list[TestCase], list[ItemListEntry], list[TestPatternFactor], list[TestPatternRow], int]:
    with stage(log, "test_case_generator", cluster_id=cluster.cluster_id):
        if is_mock(llm):
            log.info("MOCK LLM mode -- deterministic two-test-case draft (functionality_check + boundary_value_check)")
            batch = _mock_generate(cluster, requirements_by_id)
        else:
            structured = llm.with_structured_output(_GenerationBatch)
            reqs_text = "\n".join(f"- {rid}: {requirements_by_id[rid].raw_text}" for rid in cluster.requirement_ids if rid in requirements_by_id)
            prompt = (
                f"{domain_prompt_text}\n\n{SYSTEM_PROMPT}\n\n{config.project_guideline_text}\n\n"
                f"Cluster {cluster.cluster_id} ({cluster.rationale}):\n{reqs_text}"
            )
            batch = structured.invoke(prompt)

        test_cases: list[TestCase] = []
        item_list_entries: list[ItemListEntry] = []
        sequence = sequence_start
        for draft in batch.test_cases:
            tc_id = make_id(config, sequence)
            sequence += 1
            test_case, test_type = normalize_and_finalize(draft, tc_id, cluster.requirement_ids)
            test_cases.append(test_case)
            item_list_entries.append(
                ItemListEntry(
                    feature_name=test_case.feature, test_case_id=test_case.id,
                    applicable_variants=[test_case.variant] if test_case.variant else [],
                    execution_required=True, test_type=test_type,
                )
            )
            log.info("  generated %s (%d steps, feature=%s)", test_case.id, len(test_case.steps), test_case.feature)

        types_covered = sorted({e.test_type for e in item_list_entries if e.test_type})
        log.info("  cluster %s: %d test case(s), test-type coverage (internal only) = %s", cluster.cluster_id, len(test_cases), types_covered)
        log_data(log, f"test_cases[{cluster.cluster_id}]", test_cases)

        return test_cases, item_list_entries, batch.test_pattern_factors, batch.test_pattern_rows, sequence
