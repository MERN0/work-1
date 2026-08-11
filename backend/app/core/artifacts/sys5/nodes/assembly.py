"""Turning model output into canonical test cases.

The model supplies only the judgement-bearing fields. Step numbers, the execute flag,
test-case ids, the feature label and the requirement-id column are filled in here, from
the profile and the traced requirement — mechanical fields the model cannot get wrong
because it never sees them.
"""

from __future__ import annotations

from ..models import (
    FeatureIdentity,
    Phase,
    Requirement,
    TestCase,
    TestCasePlan,
    TestStep,
)
from ..projects import ProjectProfile
from ..prompts import GeneratedStep
from ..utils.text import clean


def build_test_case(
    steps: list[GeneratedStep],
    plan: TestCasePlan,
    requirement: Requirement,
    identity: FeatureIdentity,
    profile: ProjectProfile,
    index: int,
) -> TestCase:
    """Assemble one canonical test case."""
    requirement_ids = profile.requirement_id_value(
        requirement.section_no, requirement.requirement_id
    )

    case = TestCase(
        tc_id=profile.test_case_id(index, identity.label),
        feature=identity.label,
        variant=plan.variant or requirement.variant or "",
        requirement_ids=requirement_ids,
        all_requirement_ids=[
            i for i in (requirement.requirement_id, requirement.section_no) if i
        ],
        priority=plan.priority or requirement.priority or profile.default_priority,
        mode_of_execution=profile.default_mode_of_execution,
        description=plan.description or plan.aspect,
        aspect=plan.aspect,
        test_type=plan.test_type or "Normal_System",
        steps=[_to_step(s, profile) for s in steps],
    )

    _ensure_markers(case, profile)
    _apply_traceability_remark(case, requirement, profile)
    case.renumber()
    return case


def _to_step(generated: GeneratedStep, profile: ProjectProfile) -> TestStep:
    """Convert a model-supplied step into the canonical form."""
    return TestStep(
        phase=generated.phase,
        text=clean(generated.text),
        parameter=clean(generated.parameter),
        parameter_unit=clean(generated.parameter_unit),
        expected=clean(generated.expected),
        expected_unit=clean(generated.expected_unit),
        execute=profile.execute_value,
        remark=clean(generated.remark),
    )


def _ensure_markers(case: TestCase, profile: ProjectProfile) -> None:
    """Add the bookend markers when the model omitted them.

    Deterministically repairable, so it is fixed here rather than spending a correction
    round on it — that budget is better used on problems only the model can fix.
    """
    _ensure_marker(case, profile, profile.start_marker, Phase.PRECONDITION, at_start=True)
    _ensure_marker(case, profile, profile.end_marker, Phase.POSTCONDITION, at_start=False)


def _ensure_marker(
    case: TestCase, profile: ProjectProfile, text: str, phase: Phase, at_start: bool
) -> None:
    """Make sure ``text`` is the first (or last) step, inserting or repositioning it."""
    if not text:
        return

    edge = None
    if case.steps:
        edge = case.steps[0] if at_start else case.steps[-1]
    if edge is not None and edge.text == text:
        return  # already exactly where it should be

    existing = next((s for s in case.steps if s.text == text), None)
    if existing is not None:
        case.steps.remove(existing)
        existing.phase = phase
        marker = existing
    else:
        which = "Start" if at_start else "End"
        marker = TestStep(
            phase=phase,
            text=text,
            execute=profile.execute_value,
            remark=f"{which} of the qualification test case execution",
        )

    if at_start:
        case.steps.insert(0, marker)
    else:
        case.steps.append(marker)


def _apply_traceability_remark(
    case: TestCase, requirement: Requirement, profile: ProjectProfile
) -> None:
    """Carry the identifier that did not go in the column into the first step's remark.

    Whichever of the DOORS id / section number the profile did not write to the
    ``Requirement IDs`` column would otherwise be lost, breaking the trace back to
    DOORS.
    """
    other = profile.requirement_id_remark(requirement.section_no, requirement.requirement_id)
    if not other or not case.steps:
        return
    first = case.steps[0]
    if other not in first.remark:
        first.remark = f"{first.remark} (traces to {other})".strip()
