"""The generator prompt: write the steps for one planned test case."""

from __future__ import annotations

from ..models import FeatureContext, Requirement, TestCasePlan

_TEMPLATE = """## Feature
{feature}

## Requirement under test
Requirement ID: {requirement_id}
Section:        {section}

{text}

Verification criteria: {criteria}

## The test case to write
Aspect:        {aspect}
Description:   {description}
Values to exercise: {boundaries}
Precondition:  {precondition}
Action:        {action}
Postcondition: {postcondition}

## Reference data — the only names you may use
{context}

## Legal names (exhaustive)
Any name you write in a step must appear in this list, spelled exactly as shown:
{vocabulary}

## Your task
Write the ordered steps for this one test case, and only this one.

Start with {start_marker} in the PRECONDITION phase and finish with {end_marker} in the \
POSTCONDITION phase. Put the system into a defined starting state before acting: power \
and key state, direction, brake, pedals at rest. Then apply the stimulus for this \
aspect and verify the required behaviour with explicit expected values. Then restore the \
system — release what you applied, return switches to neutral, power down.

Exercise the values listed above explicitly; they are what this case exists to check. \
After a stimulus, insert a Wait long enough for the system to respond before verifying, \
and say in the remark why that delay is needed.

Do not number the steps — numbering is applied afterwards. Do not write a step whose \
name is not in the legal list above.
"""


def generator_prompt(
    requirement: Requirement,
    feature: FeatureContext,
    plan: TestCasePlan,
    context: str,
    vocabulary: list[str],
    start_marker: str,
    end_marker: str,
) -> str:
    """Build the user message for one test-case generation call."""
    return _TEMPLATE.format(
        feature=feature.render(max_chars=1500),
        requirement_id=requirement.requirement_id or "-",
        section=requirement.section_no or "-",
        text=requirement.text,
        criteria=requirement.verification_criteria or "-",
        aspect=plan.aspect,
        description=plan.description,
        boundaries=", ".join(plan.ranges_or_boundaries) or "-",
        precondition=plan.precondition_outline or "-",
        action=plan.action_outline or "-",
        postcondition=plan.postcondition_outline or "-",
        context=context,
        vocabulary=", ".join(vocabulary),
        start_marker=start_marker,
        end_marker=end_marker,
    )
