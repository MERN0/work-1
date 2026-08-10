"""The test-step grammar.

A legal step is exactly one of:

* ``Test_start`` / ``End_of_test``            — the bookend markers
* ``Wait``                                     — parameter column holds milliseconds
* ``Set <name>``                               — parameter column holds the value
* ``Verify <name>``                            — expected column holds the value
* ``Lib_<Fn> <signal>(k=v, ...)``              — signature must exist in *Library List*
* ``Compound <Name>``                          — block must exist in *Compound Commands*

Parsing is deliberately strict and total: anything that does not match a production is
reported rather than coerced, because a step the parser had to guess at is a step nobody
can verify.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from ..models import END_OF_TEST, TEST_START, TestStep


class StepKind(StrEnum):
    """Which production a step matched."""

    MARKER = "marker"
    WAIT = "wait"
    SET = "set"
    VERIFY = "verify"
    LIBRARY = "library"
    COMPOUND = "compound"
    INVALID = "invalid"


#: ``Lib_Ramp Accelerator_Sensor(Start=0,Stop=30,Step=1,Time=100)`` — the signal token
#: between the function name and the parenthesis is optional.
_LIBRARY_RE = re.compile(
    r"^(?P<fn>Lib_\w+)\s*(?P<signal>[A-Za-z_]\w*)?\s*\((?P<args>[^()]*)\)$"
)
_COMPOUND_RE = re.compile(r"^Compound\s+(?P<name>\S.*)$")
_VERB_RE = re.compile(r"^(?P<verb>[A-Za-z_]\w*)(?:\s+(?P<target>\S.*))?$")


@dataclass(slots=True)
class ParsedStep:
    """The structured form of a step's text."""

    kind: StepKind
    verb: str = ""
    target: str = ""
    #: For library calls: the keyword/positional arguments, in declaration order.
    arguments: dict[str, str] = field(default_factory=dict)
    positional: list[str] = field(default_factory=list)
    raw: str = ""
    error: str = ""

    @property
    def is_valid(self) -> bool:
        return self.kind is not StepKind.INVALID


def parse_step(text: str, allowed_verbs: tuple[str, ...]) -> ParsedStep:
    """Parse one step's text against the grammar.

    ``allowed_verbs`` comes from the project profile, so a project that permits a
    different primitive set needs no change here.
    """
    raw = (text or "").strip()
    if not raw:
        return ParsedStep(kind=StepKind.INVALID, raw=raw, error="step text is empty")

    if raw in {TEST_START, END_OF_TEST}:
        return ParsedStep(kind=StepKind.MARKER, verb=raw, raw=raw)

    if match := _LIBRARY_RE.match(raw):
        arguments: dict[str, str] = {}
        positional: list[str] = []
        for chunk in match.group("args").split(","):
            argument = chunk.strip()
            if not argument:
                continue
            if "=" in argument:
                key, _, value = argument.partition("=")
                arguments[key.strip()] = value.strip()
            else:
                positional.append(argument)
        return ParsedStep(
            kind=StepKind.LIBRARY,
            verb=match.group("fn"),
            target=(match.group("signal") or "").strip(),
            arguments=arguments,
            positional=positional,
            raw=raw,
        )

    if match := _COMPOUND_RE.match(raw):
        return ParsedStep(
            kind=StepKind.COMPOUND, verb="Compound", target=match.group("name").strip(), raw=raw
        )

    match = _VERB_RE.match(raw)
    if not match:
        return ParsedStep(kind=StepKind.INVALID, raw=raw, error=f"unrecognised step {raw!r}")

    verb = match.group("verb")
    target = (match.group("target") or "").strip()
    canonical = next((v for v in allowed_verbs if v.lower() == verb.lower()), "")

    if not canonical:
        return ParsedStep(
            kind=StepKind.INVALID,
            verb=verb,
            target=target,
            raw=raw,
            error=(
                f"{verb!r} is not an allowed keyword; use one of "
                f"{', '.join(allowed_verbs)}, Lib_<Function>(...) or Compound <Name>"
            ),
        )

    if canonical.lower() == "wait":
        if target:
            return ParsedStep(
                kind=StepKind.INVALID,
                verb=canonical,
                target=target,
                raw=raw,
                error="Wait takes no target; put the duration in the Parameter Settings column",
            )
        return ParsedStep(kind=StepKind.WAIT, verb=canonical, raw=raw)

    if not target:
        return ParsedStep(
            kind=StepKind.INVALID,
            verb=canonical,
            raw=raw,
            error=f"{canonical} requires a signal or command name",
        )

    kind = StepKind.SET if canonical.lower() == "set" else StepKind.VERIFY
    return ParsedStep(kind=kind, verb=canonical, target=target, raw=raw)


def parse_all(steps: list[TestStep], allowed_verbs: tuple[str, ...]) -> list[ParsedStep]:
    """Parse every step of a test case."""
    return [parse_step(step.text, allowed_verbs) for step in steps]
