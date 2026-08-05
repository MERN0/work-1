from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

Phase = Literal["precondition", "action", "postcondition"]

# Grammar note (ARCHITECTURE.md Sec4.4/Sec8 open Q3): the reference workbook uses a
# vocabulary well beyond set/wait/verify (Test_Start, End_of_Test, Compound_*,
# Wait_Until_*, function-call steps). `keyword` is deliberately a free-form str
# validated against config/step_grammar.yaml at runtime, not a hardcoded Literal,
# so the allowed vocabulary can be corrected without a schema change.
BRACKET_START = "Test_Start"
BRACKET_END = "End_of_Test"


class TestStep(BaseModel):
    step_no: int
    phase: Phase
    keyword: str
    raw_text: str
    parameters: dict[str, str] | None = None
    parameter_units: str | None = None
    expected_value: str | None = None
    expected_units: str | None = None
    execute: bool = True
    remarks: str | None = None


class TestCase(BaseModel):
    id: str
    feature: str
    module: str | None = None
    variant: str | None = None
    traceability: list[str] = Field(default_factory=list, description="requirement IDs")
    objective: str
    description: str
    precondition: str | None = None
    test_input_data: str | None = None
    steps: list[TestStep]
    expected_results: list[str] = Field(default_factory=list)
    mode_of_execution: str = "HIL"
    priority: str | None = None
    odc_trigger: str | None = None
    needs_review: bool = False

    @model_validator(mode="after")
    def _enforce_step_bracketing(self) -> "TestCase":
        # Hard rule (user-specified, not open for interpretation): step 1 is
        # always Test_Start, the last step is always End_of_Test, regardless of
        # phase count or how many steps sit between them.
        if not self.steps:
            raise ValueError(f"TestCase {self.id} has no steps")
        if self.steps[0].keyword != BRACKET_START:
            raise ValueError(
                f"TestCase {self.id}: step 1 must be '{BRACKET_START}', got '{self.steps[0].keyword}'"
            )
        if self.steps[-1].keyword != BRACKET_END:
            raise ValueError(
                f"TestCase {self.id}: last step must be '{BRACKET_END}', got '{self.steps[-1].keyword}'"
            )
        return self


class ItemListEntry(BaseModel):
    """Index-sheet row (Item_List tab). `test_type` is intentionally NOT written
    to the output sheet (ARCHITECTURE.md Sec8 open Q12) -- kept here only so the
    generator can reason about / verify test-type coverage internally."""

    feature_name: str
    test_case_id: str
    applicable_variants: list[str] = Field(default_factory=list)
    execution_required: bool = True
    remarks: str | None = None
    test_type: str | None = Field(
        default=None,
        description="internal-only coverage tag (functionality/stress/boundary/invalid_values/load); not serialized to Item_List output columns",
    )


class ConfigurableParameterEntry(BaseModel):
    name: str
    description: str
    values_by_variant: dict[str, str] = Field(default_factory=dict)
