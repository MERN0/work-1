"""Semantic rules: are the *values* a step carries actually legal?

Grammar and vocabulary establish that a step is well-formed and references real names.
These checks go one level deeper — that a ``Wait`` really holds milliseconds, that a
``Set`` value is one the model accepts or lies inside the parameter's declared range,
and that an expected value quotes a tolerance that exists.
"""

from __future__ import annotations

import re

from ..indexing import VocabularyIndex
from ..models import AppParameter, ModelSignal, TestCase, ValidationIssue, VocabKind
from ..utils.text import clean, normalize
from .grammar import ParsedStep, StepKind

#: A tolerance reference inside an expected value: ``10 (Config_Tol_Spd)``. Public
#: because the Configurable_Parameters output sheet reuses it to find every tolerance a
#: run's steps actually reference.
TOLERANCE_REF_RE = re.compile(r"\(\s*(?P<name>[A-Za-z_]\w*)\s*\)")

#: A leading numeric value, optionally signed/decimal, possibly with a comparison.
_NUMERIC_RE = re.compile(r"^[<>]?/?=?\s*(?P<value>[-+]?\d+(?:\.\d+)?)")

#: Values that mean "no constraint" in the parameter sheets.
_UNSET = {"", "-", "--", "n/a", "na", "tbd", "none"}


def _as_number(value: str) -> float | None:
    match = _NUMERIC_RE.match(clean(value))
    if not match:
        return None
    try:
        return float(match.group("value"))
    except ValueError:
        return None


def check_semantics(
    case: TestCase, parsed: list[ParsedStep], index: VocabularyIndex
) -> list[ValidationIssue]:
    """Validate the parameter and expected-value columns of every step."""
    issues: list[ValidationIssue] = []
    tolerance_names = {normalize(t.name) for t in index.of_kind(VocabKind.TOLERANCE)}

    for step, node in zip(case.steps, parsed, strict=True):
        if not node.is_valid:
            continue

        match node.kind:
            case StepKind.WAIT:
                issues.extend(_check_wait(step))
            case StepKind.SET:
                issues.extend(_check_set(step, node, index))
            case StepKind.VERIFY:
                issues.extend(_check_verify(step, node, index, tolerance_names))
            case StepKind.MARKER:
                issues.extend(_check_marker(step))
            case _:
                pass

        issues.extend(_check_tolerance_refs(step, tolerance_names, index))

    return issues


def _check_marker(step) -> list[ValidationIssue]:
    """Markers carry no parameter or expected value."""
    if step.parameter or step.expected:
        return [
            ValidationIssue(
                code="MARKER_HAS_VALUES",
                step_no=step.step_no,
                message=f"{step.text!r} must not carry a parameter or expected value",
                suggestion="leave the Parameter Settings and Expected Value columns empty",
            )
        ]
    return []


def _check_wait(step) -> list[ValidationIssue]:
    """``Wait`` needs a positive integer duration in milliseconds."""
    raw = clean(step.parameter)
    if not raw:
        return [
            ValidationIssue(
                code="WAIT_WITHOUT_DURATION",
                step_no=step.step_no,
                message="Wait has no duration",
                suggestion="put the delay in milliseconds in the Parameter Settings column",
            )
        ]

    value = _as_number(raw)
    if value is None or value != int(value) or value <= 0:
        return [
            ValidationIssue(
                code="BAD_WAIT_DURATION",
                step_no=step.step_no,
                message=f"Wait duration {raw!r} is not a positive whole number of milliseconds",
                suggestion="use an integer such as 100, 500 or 2000",
            )
        ]

    unit = normalize(step.parameter_unit)
    if unit and unit != "ms":
        return [
            ValidationIssue(
                code="BAD_WAIT_UNIT",
                step_no=step.step_no,
                message=f"Wait unit is {step.parameter_unit!r}; durations are in milliseconds",
                suggestion="set the unit to 'ms'",
            )
        ]

    return []


def _check_set(step, node: ParsedStep, index: VocabularyIndex) -> list[ValidationIssue]:
    """``Set`` needs a value, and that value must be one the target accepts."""
    raw = clean(step.parameter)
    if not raw:
        return [
            ValidationIssue(
                code="SET_WITHOUT_VALUE",
                step_no=step.step_no,
                message=f"Set {node.target} has no value",
                suggestion="put the value to apply in the Parameter Settings column",
            )
        ]

    entry = index.resolve(node.target)
    if entry is None:
        return []  # already reported by the vocabulary check

    for record in entry.records:
        if isinstance(record, ModelSignal) and record.allowed_inputs:
            if not _matches_allowed(raw, record.allowed_inputs):
                return [
                    ValidationIssue(
                        code="VALUE_NOT_ALLOWED",
                        step_no=step.step_no,
                        message=(
                            f"{raw!r} is not an accepted input for {record.name}; the "
                            f"model accepts {', '.join(record.allowed_inputs)}"
                        ),
                        suggestion=f"use one of: {', '.join(record.allowed_inputs)}",
                    )
                ]
            return []

        if isinstance(record, AppParameter):
            if issue := _check_range(step, record, raw):
                return [issue]

    return []


def _matches_allowed(value: str, allowed: list[str]) -> bool:
    """True when ``value`` matches an allowed input, numerically or by name.

    Numeric comparison matters because the sheets store ``30`` and a step may write
    ``30.0``; enumerated inputs (``ON``, ``FWD``) compare by normalised name.
    """
    target = normalize(value)
    if any(normalize(a) == target for a in allowed):
        return True
    number = _as_number(value)
    if number is None:
        return False
    return any((other := _as_number(a)) is not None and other == number for a in allowed)


def _check_range(step, parameter: AppParameter, raw: str) -> ValidationIssue | None:
    """Reject a value outside the parameter's declared min/max.

    Only numeric values are range-checked. A non-numeric setting (``OFF``, a mode name)
    is left alone: the parameter sheets state min/max but not an enumeration of the
    symbolic values, so rejecting one would mean inventing a constraint the source data
    does not make.
    """
    value = _as_number(raw)
    if value is None:
        return None

    minimum = _bound(parameter.min_value)
    maximum = _bound(parameter.max_value)

    if minimum is not None and value < minimum:
        return ValidationIssue(
            code="VALUE_OUT_OF_RANGE",
            step_no=step.step_no,
            message=f"{raw} is below the minimum {parameter.min_value} for {parameter.name}",
            suggestion=f"use a value between {parameter.min_value} and {parameter.max_value}",
        )
    if maximum is not None and value > maximum:
        return ValidationIssue(
            code="VALUE_OUT_OF_RANGE",
            step_no=step.step_no,
            message=f"{raw} is above the maximum {parameter.max_value} for {parameter.name}",
            suggestion=f"use a value between {parameter.min_value} and {parameter.max_value}",
        )
    return None


def _bound(raw: str) -> float | None:
    """A min/max cell as a number, or ``None`` when the sheet leaves it unset."""
    return None if clean(raw).lower() in _UNSET else _as_number(raw)


def _check_verify(
    step, node: ParsedStep, index: VocabularyIndex, tolerance_names: set[str]
) -> list[ValidationIssue]:
    """``Verify`` needs an expected value; a bare assertion proves nothing."""
    if not clean(step.expected):
        return [
            ValidationIssue(
                code="VERIFY_WITHOUT_EXPECTED",
                step_no=step.step_no,
                message=f"Verify {node.target} has no expected value",
                suggestion=(
                    "put the expected value in the Expected Value column, with a tolerance "
                    "where one applies, e.g. '10 (Config_Tol_Spd)'"
                ),
            )
        ]
    return []


def _check_tolerance_refs(
    step, tolerance_names: set[str], index: VocabularyIndex
) -> list[ValidationIssue]:
    """Any ``(Config_Tol_X)`` reference must name a tolerance that exists."""
    issues: list[ValidationIssue] = []
    for field_name in ("expected", "parameter"):
        text = clean(getattr(step, field_name))
        for match in TOLERANCE_REF_RE.finditer(text):
            name = match.group("name")
            if not name.lower().startswith("config_tol"):
                continue
            if normalize(name) not in tolerance_names:
                available = sorted(r.name for r in index.of_kind(VocabKind.TOLERANCE))
                issues.append(
                    ValidationIssue(
                        code="UNKNOWN_TOLERANCE",
                        step_no=step.step_no,
                        message=f"{name!r} is not defined in the Tolerances sheet",
                        suggestion=(
                            f"use one of: {', '.join(available)}"
                            if available
                            else "remove the tolerance reference"
                        ),
                    )
                )
    return issues
