"""The canonical, format-agnostic test-case model.

Nothing in this module knows about columns, sheets or Excel. Output templates map
these objects onto whatever layout a project needs, which is what lets a second
output format drop in without touching generation or validation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

#: The two bookend steps every TMHC test case must have.
TEST_START = "Test_start"
END_OF_TEST = "End_of_test"


class Phase(StrEnum):
    """The three parts a test case is divided into."""

    PRECONDITION = "PRECONDITION"
    ACTION = "ACTION"
    POSTCONDITION = "POSTCONDITION"

    @classmethod
    def ordered(cls) -> list[Phase]:
        """Phases in their mandatory execution order."""
        return [cls.PRECONDITION, cls.ACTION, cls.POSTCONDITION]

    @property
    def order(self) -> int:
        return Phase.ordered().index(self)


class TestStep(BaseModel):
    """A single row of a test case.

    ``text`` holds the step exactly as it should appear in the "Test steps" column —
    e.g. ``Verify CAN_Main_DispSpeed`` or ``Lib_Ramp Accelerator_Sensor(Start=0,Stop=30,
    Step=1,Time=100)``. The grammar validator parses it; nothing here interprets it.
    """

    #: Stops pytest collecting this as a test class because of its name.
    __test__ = False

    model_config = ConfigDict(extra="forbid")

    step_no: int = 0
    phase: Phase
    text: str
    parameter: str = ""
    parameter_unit: str = ""
    expected: str = ""
    expected_unit: str = ""
    execute: str = "Yes"
    remark: str = ""

    def is_bookend(self) -> bool:
        """True for the ``Test_start`` / ``End_of_test`` markers."""
        return self.text.strip() in {TEST_START, END_OF_TEST}


class TestCasePlan(BaseModel):
    """A planned test case, before its steps exist.

    Produced by the planner LLM call; one plan becomes one generator call.
    """

    #: Stops pytest collecting this as a test class because of its name.
    __test__ = False

    model_config = ConfigDict(extra="ignore")

    aspect: str = Field(description="The single behaviour or range this test case covers")
    description: str = Field(description="The 'Test Case Description' column text")
    ranges_or_boundaries: list[str] = Field(
        default_factory=list,
        description="Concrete values, ranges or boundaries this case exercises",
    )
    priority: str = "P1"
    variant: str = ""
    #: "Boundary" when the case specifically probes a stated limit or edge value,
    #: "Normal_System" for ordinary behaviour coverage. Drives the Item_List "Test Type"
    #: column; a classification judgement, not a vocabulary term, so the planner decides it.
    test_type: str = "Normal_System"
    precondition_outline: str = ""
    action_outline: str = ""
    postcondition_outline: str = ""


class ValidationIssue(BaseModel):
    """A machine-readable validation failure, consumable by the repair prompt."""

    model_config = ConfigDict(extra="forbid")

    code: str
    message: str
    step_no: int | None = None
    suggestion: str = ""

    def render(self) -> str:
        where = f"step {self.step_no}" if self.step_no is not None else "test case"
        line = f"[{self.code}] {where}: {self.message}"
        if self.suggestion:
            line += f" -> {self.suggestion}"
        return line


class TestCase(BaseModel):
    """A complete, renderable test case."""

    #: Stops pytest collecting this as a test class because of its name.
    __test__ = False

    model_config = ConfigDict(extra="ignore")

    tc_id: str = ""
    feature: str = ""
    variant: str = ""
    #: The value written to the "Requirement IDs" column (profile decides which form).
    requirement_ids: str = ""
    #: Every requirement identifier associated with this case, for traceability.
    all_requirement_ids: list[str] = Field(default_factory=list)
    priority: str = "P1"
    mode_of_execution: str = "Automated"
    description: str = ""
    aspect: str = ""
    #: "Boundary" or "Normal_System" — carried from the plan; used by the Item_List sheet.
    test_type: str = "Normal_System"
    steps: list[TestStep] = Field(default_factory=list)
    #: Unresolved issues after the repair budget is exhausted. Empty on a clean case.
    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.issues

    def steps_in_phase(self, phase: Phase) -> list[TestStep]:
        return [s for s in self.steps if s.phase is phase]

    def renumber(self) -> None:
        """Assign contiguous 1..N step numbers in phase order.

        Numbering runs across the whole case — preconditions, actions and
        postconditions share one sequence that ends at ``End_of_test``.
        """
        self.steps.sort(key=lambda s: (s.phase.order, s.step_no if s.step_no else 0))
        for index, step in enumerate(self.steps, start=1):
            step.step_no = index


class RunSummary(BaseModel):
    """What happened during a run — logged and surfaced to the caller."""

    sheet: str = ""
    feature_title: str = ""
    requirements_scanned: int = 0
    requirements_selected: int = 0
    test_cases_planned: int = 0
    test_cases_generated: int = 0
    test_cases_valid: int = 0
    test_cases_with_issues: int = 0
    #: Generated but rejected outright — an invented name or unparseable grammar
    #: survived the repair budget. Not in the workbook; kept in the run's intermediates.
    test_cases_rejected: int = 0
    llm_calls: int = 0
    output_path: str = ""

    def render(self) -> str:
        return (
            f"sheet={self.sheet!r} feature={self.feature_title!r} "
            f"reqs={self.requirements_selected}/{self.requirements_scanned} "
            f"planned={self.test_cases_planned} generated={self.test_cases_generated} "
            f"valid={self.test_cases_valid} with_issues={self.test_cases_with_issues} "
            f"rejected={self.test_cases_rejected} llm_calls={self.llm_calls}"
        )
