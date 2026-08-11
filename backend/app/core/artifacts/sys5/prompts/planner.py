"""The planner prompt: decide how many test cases a requirement needs, and what each covers."""

from __future__ import annotations

from ..models import FeatureContext, Requirement

_TEMPLATE = """## Feature
{feature}

## Requirement under test
Requirement ID: {requirement_id}
Section:        {section}
Variant:        {variant}
Priority:       {priority}
Verification:   {verification_method} / {verification_stage}
Heading:        {heading}

{text}

Verification criteria: {criteria}

## Data available for this requirement
These are the only signals, commands and parameters that exist for this feature. If a \
test you have in mind cannot be expressed with them, do not plan it.

{available}

## Your task
Plan every SYS5 test case this requirement needs — not a representative sample, all of \
them. Work through the requirement clause by clause and enumerate:

- each distinct behaviour it states;
- each numeric range, limit or threshold, and its boundaries (at the limit, just inside, \
just outside);
- each state, mode or direction the behaviour applies to (forward and reverse, loaded and \
unloaded, each configuration value);
- each transition into and out of the behaviour;
- the negative cases: what must *not* happen, and what happens when the condition is \
absent or the input is out of range.

One test case covers one aspect. A requirement stating a limit in both travel directions \
needs at least two cases, not one that changes direction halfway through. Where the \
requirement gives a configurable range, cover its minimum, its maximum and a value \
between them.

Set `ranges_or_boundaries` to the concrete values the case will exercise, written the way \
they should appear in the steps (for example "10 km/h", "0.5 km/h", "20 deg").

Set `test_type` to "Boundary" for a case that exists specifically to probe a stated \
limit, edge value or out-of-range condition, and "Normal_System" for ordinary behaviour \
coverage.

In `coverage_rationale`, state briefly how the set of cases covers the whole requirement, \
and name explicitly anything the available data does not let you test.
"""


def planner_prompt(
    requirement: Requirement, feature: FeatureContext, available: str
) -> str:
    """Build the user message for the planning call."""
    return _TEMPLATE.format(
        feature=feature.render(),
        requirement_id=requirement.requirement_id or "-",
        section=requirement.section_no or "-",
        variant=requirement.variant or "-",
        priority=requirement.priority or "-",
        verification_method=requirement.verification_method or "-",
        verification_stage=requirement.verification_stage or "-",
        heading=requirement.heading or "-",
        text=requirement.text,
        criteria=requirement.verification_criteria or "-",
        available=available,
    )
