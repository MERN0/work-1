"""The repair prompt: fix a test case that failed validation.

Sent only the failing case, the issue list and the legal names — not the whole context
pack. A repair round is a narrow, mechanical correction, and giving the model room to
re-imagine the test case is how a correction turns into a regression.
"""

from __future__ import annotations

import json

from ..models import TestCase
from ..validation import ValidationResult

_TEMPLATE = """The test case below failed automated validation. Fix exactly the problems \
listed and change nothing else.

## Test case
Aspect:      {aspect}
Description: {description}

## Current steps
{steps}

## Validation failures
{issues}

## Legal names (exhaustive)
Any name in a step must appear here, spelled exactly as shown:
{vocabulary}

## Your task
Return the corrected, complete list of steps — every step of the test case, not only the \
ones you changed.

Fix each listed failure at its source. If a name is rejected, replace it with the \
suggested legal name, or remove the step when no legal equivalent exists. If a value is \
out of range or not an accepted input, use one the reference data permits. If a phase or \
a marker is missing, add it. If a remark is too thin, write a real one explaining what \
the step establishes.

Keep the steps that already pass exactly as they are. Do not add new checks, do not \
reorder passing steps, and do not change the purpose of the test case.
"""


def repair_prompt(case: TestCase, result: ValidationResult, vocabulary: list[str]) -> str:
    """Build the user message for a repair call."""
    steps = json.dumps(
        [
            {
                "phase": step.phase.value,
                "text": step.text,
                "parameter": step.parameter,
                "parameter_unit": step.parameter_unit,
                "expected": step.expected,
                "expected_unit": step.expected_unit,
                "remark": step.remark,
            }
            for step in case.steps
        ],
        indent=2,
        ensure_ascii=False,
    )

    return _TEMPLATE.format(
        aspect=case.aspect or "-",
        description=case.description or "-",
        steps=steps,
        issues=result.render(),
        vocabulary=", ".join(vocabulary),
    )
