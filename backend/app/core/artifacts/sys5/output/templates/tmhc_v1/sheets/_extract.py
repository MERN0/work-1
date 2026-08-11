"""Shared helpers for deriving auxiliary-sheet content from the rendered test cases.

Nothing here invents data: every value comes from re-parsing the steps the pipeline
already validated, using the same grammar the validator uses. A name can appear on
Item_List, Configurable_Parameters or Test Pattern only because it is already on the
test-case sheet — these are views over that data, never a second source of truth.
"""

from __future__ import annotations

from .....models import TestCase
from .....validation.grammar import StepKind, parse_step
from .....validation.semantics import TOLERANCE_REF_RE


def used_names(cases: list[TestCase], allowed_verbs: tuple[str, ...]) -> list[str]:
    """Every Set/Verify target and ``Config_Tol_*`` reference used across ``cases``.

    First-seen order, deduplicated. Compound and library calls are excluded — they are
    macros/actions, not configurable values.
    """
    seen: dict[str, None] = {}
    for case in cases:
        for step in case.steps:
            node = parse_step(step.text, allowed_verbs)
            if node.kind in (StepKind.SET, StepKind.VERIFY) and node.target:
                seen.setdefault(node.target, None)
            for text in (step.parameter, step.expected):
                for match in TOLERANCE_REF_RE.finditer(text or ""):
                    name = match.group("name")
                    if name.lower().startswith("config_tol"):
                        seen.setdefault(name, None)
    return list(seen)


def set_factor_matrix(
    cases: list[TestCase], allowed_verbs: tuple[str, ...]
) -> dict[str, dict[int, str]]:
    """``Set`` target name -> ``{case_index: value used}``, across ``cases``.

    Only ``Set`` steps with a concrete value count as a "factor" — this is what Test
    Pattern varies row to row, distinct from the read-only ``Verify`` assertions.
    """
    factors: dict[str, dict[int, str]] = {}
    for index, case in enumerate(cases):
        for step in case.steps:
            node = parse_step(step.text, allowed_verbs)
            if node.kind is StepKind.SET and node.target and step.parameter:
                factors.setdefault(node.target, {})[index] = step.parameter
    return factors
