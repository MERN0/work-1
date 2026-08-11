"""Response schemas the model must fill.

Kept deliberately narrow. The model supplies only what requires judgement — which
aspects to test, and the ordered steps with their values and remarks. Step numbers, the
execute flag, test-case ids and every other mechanical field are assigned in Python,
because a field the model cannot get wrong is a class of defect that cannot occur.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..models import Phase


class PlannedCase(BaseModel):
    """One test case the planner intends to write."""

    model_config = ConfigDict(extra="ignore")

    aspect: str = Field(description="The single behaviour, range or boundary this case covers")
    description: str = Field(
        description="One or two sentences for the 'Test Case Description' column"
    )
    ranges_or_boundaries: list[str] = Field(
        default_factory=list,
        description="Concrete values this case exercises, e.g. ['10 km/h', '0 km/h']",
    )
    priority: str = Field(default="P1", description="P1, P2 or P3")
    variant: str = Field(default="", description="Variant from the requirement, e.g. A1")
    test_type: str = Field(
        default="Normal_System",
        description=(
            "'Boundary' when this case exists specifically to probe a stated limit, "
            "edge value or out-of-range condition; 'Normal_System' for ordinary "
            "behaviour coverage"
        ),
    )
    precondition_outline: str = Field(default="", description="One line: the starting state")
    action_outline: str = Field(default="", description="One line: the stimulus and checks")
    postcondition_outline: str = Field(default="", description="One line: how the system is restored")


class PlanResponse(BaseModel):
    """The planner's full answer for one requirement."""

    model_config = ConfigDict(extra="ignore")

    coverage_rationale: str = Field(
        default="",
        description="Why this set of cases covers every testable aspect of the requirement",
    )
    test_cases: list[PlannedCase] = Field(default_factory=list)


class GeneratedStep(BaseModel):
    """One row of a generated test case."""

    model_config = ConfigDict(extra="ignore")

    phase: Phase = Field(description="PRECONDITION, ACTION or POSTCONDITION")
    text: str = Field(
        description=(
            "The step exactly as written in the 'Test steps' column: Test_start, "
            "End_of_test, Wait, 'Set <name>', 'Verify <name>', "
            "'Lib_<Function> <signal>(...)' or 'Compound <Name>'"
        )
    )
    parameter: str = Field(default="", description="Parameter Settings column")
    parameter_unit: str = Field(default="", description="Units column for the parameter")
    expected: str = Field(default="", description="Expected Value column")
    expected_unit: str = Field(default="", description="Units column for the expected value")
    remark: str = Field(
        description="Why this step exists and what it establishes — never a restatement of the step"
    )


class StepsResponse(BaseModel):
    """The generator's answer for one planned test case."""

    model_config = ConfigDict(extra="ignore")

    steps: list[GeneratedStep] = Field(default_factory=list)
