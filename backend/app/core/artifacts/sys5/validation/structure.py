"""Structural rules: bookends, numbering, phase ordering and remarks."""

from __future__ import annotations

from ..models import Phase, TestCase, ValidationIssue
from ..projects import ProjectProfile
from ..utils.text import normalize


def check_structure(case: TestCase, profile: ProjectProfile) -> list[ValidationIssue]:
    """Validate the shape of a test case, independently of what its steps say."""
    issues: list[ValidationIssue] = []

    if not case.steps:
        return [ValidationIssue(code="EMPTY_CASE", message="test case has no steps")]

    issues.extend(_check_markers(case, profile))
    issues.extend(_check_numbering(case))
    issues.extend(_check_phases(case, profile))
    issues.extend(_check_remarks(case, profile))
    issues.extend(_check_execute_column(case, profile))
    return issues


def _check_markers(case: TestCase, profile: ProjectProfile) -> list[ValidationIssue]:
    """The first step must be ``Test_start`` and the last ``End_of_test``."""
    issues: list[ValidationIssue] = []

    if profile.start_marker:
        first = case.steps[0]
        if first.text.strip() != profile.start_marker:
            issues.append(
                ValidationIssue(
                    code="MISSING_START_MARKER",
                    step_no=first.step_no,
                    message=f"the first step must be {profile.start_marker!r}, found {first.text!r}",
                    suggestion=f"insert {profile.start_marker!r} as step 1 in the PRECONDITION phase",
                )
            )
        if sum(1 for s in case.steps if s.text.strip() == profile.start_marker) > 1:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_START_MARKER",
                    message=f"{profile.start_marker!r} appears more than once",
                )
            )

    if profile.end_marker:
        last = case.steps[-1]
        if last.text.strip() != profile.end_marker:
            issues.append(
                ValidationIssue(
                    code="MISSING_END_MARKER",
                    step_no=last.step_no,
                    message=f"the last step must be {profile.end_marker!r}, found {last.text!r}",
                    suggestion=(
                        f"append {profile.end_marker!r} as the final step of the "
                        "POSTCONDITION phase"
                    ),
                )
            )
        if sum(1 for s in case.steps if s.text.strip() == profile.end_marker) > 1:
            issues.append(
                ValidationIssue(
                    code="DUPLICATE_END_MARKER",
                    message=f"{profile.end_marker!r} appears more than once",
                )
            )

    return issues


def _check_numbering(case: TestCase) -> list[ValidationIssue]:
    """Step numbers must run 1..N without gaps, across all three phases."""
    expected = list(range(1, len(case.steps) + 1))
    actual = [s.step_no for s in case.steps]
    if actual == expected:
        return []

    first_bad = next(
        (i for i, (a, e) in enumerate(zip(actual, expected, strict=True)) if a != e), 0
    )
    return [
        ValidationIssue(
            code="BAD_NUMBERING",
            step_no=actual[first_bad] if first_bad < len(actual) else None,
            message=(
                f"step numbers must be contiguous 1..{len(case.steps)} across the whole "
                f"test case; got {actual}"
            ),
            suggestion="renumber sequentially, continuing across phase boundaries",
        )
    ]


def _check_phases(case: TestCase, profile: ProjectProfile) -> list[ValidationIssue]:
    """Phases must appear in order and, when required, all be populated."""
    issues: list[ValidationIssue] = []

    seen_order = [s.phase for s in case.steps]
    ranks = [p.order for p in seen_order]
    if ranks != sorted(ranks):
        issues.append(
            ValidationIssue(
                code="PHASE_OUT_OF_ORDER",
                message=(
                    "steps must be grouped in the order PRECONDITION -> ACTION -> "
                    "POSTCONDITION"
                ),
                suggestion="reorder the steps so each phase forms one contiguous block",
            )
        )

    if profile.require_all_phases:
        for phase in Phase.ordered():
            if not case.steps_in_phase(phase):
                issues.append(
                    ValidationIssue(
                        code="MISSING_PHASE",
                        message=f"the {phase.value} phase has no steps",
                        suggestion=(
                            f"add the {phase.value} steps; every test case must set up, act "
                            "and then restore the system"
                        ),
                    )
                )

    return issues


def _check_remarks(case: TestCase, profile: ProjectProfile) -> list[ValidationIssue]:
    """Every row needs a substantive remark that is not a restatement of the step."""
    issues: list[ValidationIssue] = []
    for step in case.steps:
        remark = step.remark.strip()
        if len(remark) < profile.min_remark_chars:
            issues.append(
                ValidationIssue(
                    code="MISSING_REMARK",
                    step_no=step.step_no,
                    message=(
                        f"remark is {len(remark)} characters; at least "
                        f"{profile.min_remark_chars} are required"
                    ),
                    suggestion="explain why this step exists and what it establishes",
                )
            )
        elif normalize(remark) == normalize(step.text):
            issues.append(
                ValidationIssue(
                    code="TRIVIAL_REMARK",
                    step_no=step.step_no,
                    message="the remark just repeats the step text",
                    suggestion="describe the intent or the expected system behaviour instead",
                )
            )
    return issues


def _check_execute_column(case: TestCase, profile: ProjectProfile) -> list[ValidationIssue]:
    """The "Whether to execute the command" column must carry the profile's value."""
    if not profile.execute_value:
        return []
    return [
        ValidationIssue(
            code="BAD_EXECUTE_FLAG",
            step_no=step.step_no,
            message=(
                f"'Whether to execute the command' is {step.execute!r}, expected "
                f"{profile.execute_value!r}"
            ),
            suggestion=f"set it to {profile.execute_value!r}",
        )
        for step in case.steps
        if step.execute.strip().lower() != profile.execute_value.lower()
    ]
