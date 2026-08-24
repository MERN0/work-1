"""Deterministic linking of a requirement to the data needed to test it.

Tracing never asks the model what a requirement relates to. It combines three
independent signals, strongest first:

1. **Feature-column membership** — the master sheets carry one column per feature and a
   ``○`` mark states outright that a signal/parameter belongs to it. This is exact.
2. **Explicit identifier references** — a ``TMHC_SYSRS_*`` id written into the
   requirement text or its Source column.
3. **Name and description similarity** — token overlap plus fuzzy matching, ranked and
   thresholded, for the cases the first two miss.

Commands are then pulled in transitively: a Command List row whose ``Signal Name``
matches a traced CAN signal is itself traced, which is how ``Verify CAN_Main_DispSpeed``
becomes available to a requirement that only ever mentions "displayed speed".
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..models import (
    CanSignal,
    Command,
    CompoundCommand,
    KnowledgeBase,
    KnowledgeRecord,
    Requirement,
)
from ..utils.text import normalize, normalize_loose

logger = logging.getLogger(__name__)

#: Score awarded by each tracing signal.
SCORE_FEATURE_COLUMN = 100
SCORE_EXPLICIT_ID = 100
SCORE_NAME_IN_TEXT = 95
SCORE_TRANSITIVE = 90

#: Tokens too generic to carry meaning when matching a name against requirement text.
_STOPWORDS = frozenset(
    {
        "the", "a", "an", "of", "to", "and", "or", "for", "in", "on", "at", "by", "is",
        "be", "shall", "when", "then", "with", "from", "value", "signal", "state",
        "mode", "control", "system", "data", "com", "mdl", "can", "sen", "swh", "main",
        "tmhc", "sysrs",
    }
)

_TOKEN_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    """Meaningful lowercase tokens of a name or sentence."""
    parts = _TOKEN_SPLIT_RE.split(text or "")
    return {p.lower() for p in parts if len(p) > 2 and p.lower() not in _STOPWORDS}


@dataclass(slots=True)
class TracedItem:
    """A knowledge record linked to a requirement, with why and how strongly."""

    record: KnowledgeRecord
    score: int
    reasons: list[str] = field(default_factory=list)

    def add(self, score: int, reason: str) -> None:
        if score > self.score:
            self.score = score
        if reason not in self.reasons:
            self.reasons.append(reason)


class _Tracer:
    """Accumulates traced items for one requirement."""

    def __init__(self) -> None:
        self.items: dict[int, TracedItem] = {}

    def add(self, record: KnowledgeRecord, score: int, reason: str) -> None:
        key = id(record)
        existing = self.items.get(key)
        if existing is None:
            self.items[key] = TracedItem(record=record, score=score, reasons=[reason])
        else:
            existing.add(score, reason)

    def ranked(self, minimum: int = 0) -> list[TracedItem]:
        return sorted(
            (i for i in self.items.values() if i.score >= minimum),
            key=lambda i: (-i.score, i.record.name),
        )


def _trace_records(
    tracer: _Tracer,
    records: list[KnowledgeRecord],
    requirement: Requirement,
    feature: str,
    threshold: int,
) -> None:
    """Apply the three tracing signals to one collection of records."""
    req_text = f"{requirement.text} {requirement.heading} {requirement.verification_criteria}"
    req_norm = normalize_loose(req_text)
    req_tokens = _tokens(req_text)
    referenced = {normalize(i) for i in (*requirement.referenced_ids, requirement.requirement_id)}

    for record in records:
        # 1. feature-column membership — exact and authoritative
        if feature and feature in record.features:
            tracer.add(record, SCORE_FEATURE_COLUMN, f"feature-column:{feature}")

        # 2. explicit identifier reference in the requirement
        if referenced & {normalize(n) for n in record.all_names()}:
            tracer.add(record, SCORE_EXPLICIT_ID, "explicit-id")
        linked = getattr(record, "linked_requirement", "")
        if linked and normalize(linked) in referenced:
            tracer.add(record, SCORE_EXPLICIT_ID, "linked-requirement")

        # 3. similarity — name appearing verbatim, then token overlap, then description
        best_score, best_reason = 0, ""
        for name in record.all_names():
            name_norm = normalize_loose(name)
            if len(name_norm.replace(" ", "")) >= 4 and name_norm in req_norm:
                best_score, best_reason = SCORE_NAME_IN_TEXT, "name-in-text"
                break
            name_tokens = _tokens(name)
            if not name_tokens:
                continue
            overlap = len(name_tokens & req_tokens) / len(name_tokens)
            if overlap >= 0.5:
                score = int(60 + 35 * overlap)
                if score > best_score:
                    best_score, best_reason = score, f"token-overlap:{overlap:.0%}"

        if best_score < threshold and record.description:
            similarity = fuzz.token_set_ratio(normalize_loose(record.description), req_norm)
            if similarity >= threshold:
                best_score, best_reason = int(similarity) - 10, f"description:{int(similarity)}"

        if best_score >= threshold:
            tracer.add(record, best_score, best_reason)


def _trace_commands(
    tracer: _Tracer,
    commands: list[Command],
    traced_can: list[CanSignal],
    requirement: Requirement,
    feature: str,
    threshold: int,
) -> None:
    """Link commands to the requirement, directly and via their CAN signal.

    Command List rows carry no feature column, so the transitive path through
    ``Signal Name`` is the main way a command becomes available to a requirement.
    """
    _trace_records(tracer, list(commands), requirement, feature, threshold)

    can_names = {normalize(n) for signal in traced_can for n in signal.all_names()}
    if not can_names:
        return
    for command in commands:
        keys = {normalize(command.signal_name), normalize(command.name)}
        keys.discard("")
        if keys & can_names:
            tracer.add(command, SCORE_TRANSITIVE, "via-can-signal")


def _trace_compounds(
    tracer: _Tracer,
    compounds: list[CompoundCommand],
    traced_names: set[str],
) -> None:
    """Score compound commands by how much of their body the requirement already touches.

    Every compound stays *available* (its name is always legal); scoring only decides
    whose full body is worth spending context tokens on.
    """
    for compound in compounds:
        referenced = set()
        for step in compound.steps:
            parts = step.keyword.split(maxsplit=1)
            if len(parts) == 2:
                referenced.add(normalize(parts[1]))
        overlap = referenced & traced_names
        if overlap:
            score = int(60 + 35 * (len(overlap) / max(1, len(referenced))))
            tracer.add(compound, score, f"uses-traced-signals:{len(overlap)}")


@dataclass(slots=True)
class ContextPack:
    """Everything one requirement needs, ranked and ready to be rendered into a prompt."""

    requirement: Requirement
    feature: str
    io_signals: list[TracedItem] = field(default_factory=list)
    can_signals: list[TracedItem] = field(default_factory=list)
    commands: list[TracedItem] = field(default_factory=list)
    app_parameters: list[TracedItem] = field(default_factory=list)
    model_signals: list[TracedItem] = field(default_factory=list)
    compounds: list[TracedItem] = field(default_factory=list)
    #: Names of every compound, whether or not its body is included.
    all_compound_names: list[str] = field(default_factory=list)

    def traced_records(self) -> list[KnowledgeRecord]:
        return [
            item.record
            for group in (
                self.io_signals,
                self.can_signals,
                self.commands,
                self.app_parameters,
                self.model_signals,
                self.compounds,
            )
            for item in group
        ]

    def stats(self) -> dict[str, int]:
        return {
            "io_signals": len(self.io_signals),
            "can_signals": len(self.can_signals),
            "commands": len(self.commands),
            "app_parameters": len(self.app_parameters),
            "model_signals": len(self.model_signals),
            "compounds": len(self.compounds),
        }


def trace_requirement(
    requirement: Requirement,
    knowledge: KnowledgeBase,
    feature: str,
    threshold: int = 85,
) -> ContextPack:
    """Build the context pack for one requirement."""
    io_tracer, can_tracer, param_tracer, model_tracer = _Tracer(), _Tracer(), _Tracer(), _Tracer()

    _trace_records(io_tracer, list(knowledge.io_signals), requirement, feature, threshold)
    _trace_records(can_tracer, list(knowledge.can_signals), requirement, feature, threshold)
    _trace_records(param_tracer, list(knowledge.app_parameters), requirement, feature, threshold)

    # Model signals carry no feature column and are a small closed set — the model-side
    # actuators (key switch, direction switch, park brake, pedals) that essentially every
    # precondition and postcondition has to drive. Tracing them by name would strand a
    # test case unable to put the truck into its starting state just because the
    # requirement sentence happens not to mention the park brake, so they are all kept.
    for model_signal in knowledge.model_signals:
        model_tracer.add(model_signal, SCORE_FEATURE_COLUMN, "always-available")
    _trace_records(model_tracer, list(knowledge.model_signals), requirement, "", threshold)

    traced_can = [i.record for i in can_tracer.ranked() if isinstance(i.record, CanSignal)]
    command_tracer = _Tracer()
    _trace_commands(
        command_tracer, list(knowledge.commands), traced_can, requirement, feature, threshold
    )

    traced_names = {
        normalize(name)
        for tracer in (io_tracer, can_tracer, model_tracer, command_tracer)
        for item in tracer.ranked()
        for name in item.record.all_names()
    }
    compound_tracer = _Tracer()
    _trace_compounds(compound_tracer, list(knowledge.compounds), traced_names)

    pack = ContextPack(
        requirement=requirement,
        feature=feature,
        io_signals=io_tracer.ranked(),
        can_signals=can_tracer.ranked(),
        commands=command_tracer.ranked(),
        app_parameters=param_tracer.ranked(),
        model_signals=model_tracer.ranked(),
        compounds=compound_tracer.ranked(),
        all_compound_names=[c.name for c in knowledge.compounds],
    )
    stats = pack.stats()
    logger.info("[sys5] traced %s -> %s", requirement.requirement_id, stats)
    if stats["io_signals"] + stats["can_signals"] + stats["commands"] == 0:
        logger.warning(
            "[sys5] %s traced no I/O signals, CAN signals or commands — its steps will "
            "have nothing concrete to reference beyond the always-available model signals",
            requirement.requirement_id,
        )
    return pack


__all__ = ["ContextPack", "TracedItem", "trace_requirement"]
