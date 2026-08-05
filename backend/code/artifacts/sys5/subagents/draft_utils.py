"""Shared between test_case_generator and verification_correction_agent: the
permissive draft schema LLM output is parsed into, the bracketing
normalization (pure Python, ARCHITECTURE.md "hard rule" -- step 1 is always
Test_Start, last step is always End_of_Test), and ID generation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from config_loader import RunConfig
from logging_setup import get_logger
from schemas import TestCase, TestStep

log = get_logger("draft_utils")


class TestStepDraft(BaseModel):
    phase: str = "action"
    keyword: str
    raw_text: str
    parameters: dict[str, str] | None = None
    parameter_units: str | None = None
    expected_value: str | None = None
    expected_units: str | None = None
    execute: bool = True
    remarks: str | None = None


class TestCaseDraft(BaseModel):
    feature: str
    module: str | None = None
    variant: str | None = None
    objective: str
    description: str
    precondition: str | None = None
    test_input_data: str | None = None
    steps: list[TestStepDraft]
    expected_results: list[str] = Field(default_factory=list)
    mode_of_execution: str = "HIL"
    priority: str | None = None
    odc_trigger: str | None = None
    internal_test_type: str | None = None  # planning-only, never written to output


def make_id(config: RunConfig, sequence: int) -> str:
    fmt = config.id_format
    prefix = fmt.get("prefix", "TC")
    sep = fmt.get("separator", "_")
    width = fmt.get("sequence_width", 3)
    return f"{prefix}{sep}{sequence:0{width}d}"


def normalize_and_finalize(draft: TestCaseDraft, test_case_id: str, traceability: list[str]) -> tuple[TestCase, str | None]:
    steps: list[TestStepDraft] = list(draft.steps)

    if not steps or steps[0].keyword != "Test_Start":
        log.debug("  %s: prepending missing Test_Start bracket step", test_case_id)
        steps.insert(0, TestStepDraft(phase=steps[0].phase if steps else "precondition", keyword="Test_Start", raw_text="Test_Start"))
    if steps[-1].keyword != "End_of_Test":
        log.debug("  %s: appending missing End_of_Test bracket step", test_case_id)
        steps.append(TestStepDraft(phase=steps[-1].phase, keyword="End_of_Test", raw_text="End_of_Test"))

    final_steps: list[TestStep] = []
    for i, s in enumerate(steps, start=1):
        phase = s.phase if s.phase in ("precondition", "action", "postcondition") else "action"
        final_steps.append(
            TestStep(
                step_no=i, phase=phase, keyword=s.keyword, raw_text=s.raw_text,
                parameters=s.parameters, parameter_units=s.parameter_units,
                expected_value=s.expected_value, expected_units=s.expected_units,
                execute=s.execute, remarks=s.remarks,
            )
        )

    test_case = TestCase(
        id=test_case_id, feature=draft.feature, module=draft.module, variant=draft.variant,
        traceability=traceability, objective=draft.objective, description=draft.description,
        precondition=draft.precondition, test_input_data=draft.test_input_data, steps=final_steps,
        expected_results=draft.expected_results, mode_of_execution=draft.mode_of_execution,
        priority=draft.priority, odc_trigger=draft.odc_trigger,
    )
    return test_case, draft.internal_test_type


def test_case_to_draft(test_case: TestCase) -> TestCaseDraft:
    """Inverse of normalize_and_finalize -- used to hand an existing test case
    back to the LLM for correction without re-deriving its id/traceability."""
    return TestCaseDraft(
        feature=test_case.feature, module=test_case.module, variant=test_case.variant,
        objective=test_case.objective, description=test_case.description,
        precondition=test_case.precondition, test_input_data=test_case.test_input_data,
        steps=[
            TestStepDraft(
                phase=s.phase, keyword=s.keyword, raw_text=s.raw_text, parameters=s.parameters,
                parameter_units=s.parameter_units, expected_value=s.expected_value,
                expected_units=s.expected_units, execute=s.execute, remarks=s.remarks,
            )
            for s in test_case.steps
        ],
        expected_results=test_case.expected_results, mode_of_execution=test_case.mode_of_execution,
        priority=test_case.priority, odc_trigger=test_case.odc_trigger,
    )
