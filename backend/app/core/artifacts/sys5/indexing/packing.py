"""Rendering a context pack into prompt text within a token budget.

The on-prem model has a 100k window and the pack for a busy requirement can be large, so
rendering is budget-aware. Trimming is ordered by evidential strength: items traced by a
feature-column mark or an explicit id reference are never dropped, and fuzzy matches are
shed from the weakest upward. The model would rather see fewer, certainly-relevant
signals than a truncated list of everything.
"""

from __future__ import annotations

import logging

from ..models import (
    AppParameter,
    CanSignal,
    Command,
    CompoundCommand,
    IoSignal,
    KnowledgeBase,
    ModelSignal,
)
from ..utils.text import truncate
from .tracing import ContextPack, TracedItem

logger = logging.getLogger(__name__)

#: Items traced at or above this score are load-bearing and never trimmed.
CORE_SCORE = 90

#: Characters per token. Deliberately conservative: over-estimating the prompt costs a
#: little context, under-estimating costs the whole call.
CHARS_PER_TOKEN = 3.2

#: How many compound bodies to include at most, before budget trimming.
MAX_COMPOUND_BODIES = 8


def estimate_tokens(text: str) -> int:
    """Approximate token count of a string.

    A character heuristic rather than a real tokenizer: the on-prem model's tokenizer is
    not necessarily available locally, and the budget only needs to be safe, not exact.
    """
    return int(len(text) / CHARS_PER_TOKEN) + 1


def _split_core(items: list[TracedItem]) -> tuple[list[TracedItem], list[TracedItem]]:
    """Partition into (never-trim, trimmable-weakest-first)."""
    core = [i for i in items if i.score >= CORE_SCORE]
    optional = sorted(
        (i for i in items if i.score < CORE_SCORE), key=lambda i: i.score, reverse=True
    )
    return core, optional


def _table(title: str, headers: list[str], rows: list[list[str]]) -> str:
    """A compact pipe-delimited block. Cheaper in tokens than JSON, easy to read."""
    if not rows:
        return ""
    lines = [f"### {title}", " | ".join(headers)]
    lines.extend(" | ".join(cell or "-" for cell in row) for row in rows)
    return "\n".join(lines)


def _io_rows(items: list[TracedItem]) -> list[list[str]]:
    return [
        [r.name, r.signal_type, r.signal_id]
        for r in (i.record for i in items)
        if isinstance(r, IoSignal)
    ]


def _can_rows(items: list[TracedItem]) -> list[list[str]]:
    return [
        [r.name, r.signal_name, r.message_name, r.message_id, truncate(r.description, 80)]
        for r in (i.record for i in items)
        if isinstance(r, CanSignal)
    ]


def _command_rows(items: list[TracedItem]) -> list[list[str]]:
    return [
        [r.name, r.message_name, truncate(r.description, 80)]
        for r in (i.record for i in items)
        if isinstance(r, Command)
    ]


def _model_rows(items: list[TracedItem]) -> list[list[str]]:
    return [
        [r.name, ", ".join(r.allowed_inputs)]
        for r in (i.record for i in items)
        if isinstance(r, ModelSignal)
    ]


def _parameter_rows(items: list[TracedItem]) -> list[list[str]]:
    return [
        [r.name, r.parameter_type, r.unit, r.default_value, r.min_value, r.max_value,
         truncate(r.description, 70)]
        for r in (i.record for i in items)
        if isinstance(r, AppParameter)
    ]


def _compound_body(compound: CompoundCommand) -> str:
    lines = [f"Compound {compound.name}  ({compound.category})"]
    for step in compound.steps:
        detail = " | ".join(
            part
            for part in (step.keyword, step.parameter, step.parameter_unit, step.expected,
                         step.expected_unit)
            if part
        )
        lines.append(f"  - {detail}")
    return "\n".join(lines)


def render_vocabulary(pack: ContextPack, knowledge: KnowledgeBase) -> list[str]:
    """The flat list of names this requirement's steps may legally use.

    Handed to the generator verbatim. Anything outside it is a validation failure, so
    the list is the contract between prompt and validator.
    """
    names: list[str] = []
    for item in (
        *pack.io_signals,
        *pack.can_signals,
        *pack.commands,
        *pack.model_signals,
        *pack.app_parameters,
    ):
        names.extend(item.record.all_names())
    names.extend(c.name for c in knowledge.compounds)
    names.extend(library.name for library in knowledge.libraries)
    names.extend(tolerance.name for tolerance in knowledge.tolerances)
    return list(dict.fromkeys(n for n in names if n))


def render_context(
    pack: ContextPack,
    knowledge: KnowledgeBase,
    budget_tokens: int,
    include_compound_bodies: bool = True,
) -> str:
    """Render the pack as prompt text, trimming until it fits ``budget_tokens``."""
    io_core, io_opt = _split_core(pack.io_signals)
    can_core, can_opt = _split_core(pack.can_signals)
    cmd_core, cmd_opt = _split_core(pack.commands)
    par_core, par_opt = _split_core(pack.app_parameters)
    mdl_core, mdl_opt = _split_core(pack.model_signals)

    # Compound bodies are the most expensive and least essential section, so they are
    # the first thing dropped; the names always remain available.
    bodies = [i.record for i in pack.compounds[:MAX_COMPOUND_BODIES]] if include_compound_bodies else []

    def build(
        io_extra: int, can_extra: int, cmd_extra: int, par_extra: int, mdl_extra: int,
        body_count: int,
    ) -> str:
        blocks = [
            _table("I/O SIGNALS (Set/Verify targets)", ["Name", "Type", "Signal ID"],
                   _io_rows(io_core + io_opt[:io_extra])),
            _table("CAN SIGNALS", ["Logical Name", "Bus Signal", "Message", "ID", "Description"],
                   _can_rows(can_core + can_opt[:can_extra])),
            _table("COMMANDS (Set/Verify targets)", ["Command", "Message", "Description"],
                   _command_rows(cmd_core + cmd_opt[:cmd_extra])),
            _table("MODEL SIGNALS (Set targets)", ["Signal", "Allowed values"],
                   _model_rows(mdl_core + mdl_opt[:mdl_extra])),
            _table(
                "APPLICATION PARAMETERS",
                ["Name", "Type", "Unit", "Default", "Min", "Max", "Purpose"],
                _parameter_rows(par_core + par_opt[:par_extra]),
            ),
            _table(
                "TOLERANCES (write expected values as '<value> (Config_Tol_X)')",
                ["Name", "Unit", "+/-", "Purpose"],
                [[t.name, t.unit, f"+{t.positive}/-{t.negative}", truncate(t.description, 60)]
                 for t in knowledge.tolerances],
            ),
            _table(
                "LIBRARY FUNCTIONS (use exactly this signature)",
                ["Signature", "Description"],
                [[library.signature, truncate(library.description, 90)]
                 for library in knowledge.libraries],
            ),
            _table(
                "CONFIGURATION ENUMS",
                ["Signal", "Description", "Values"],
                [[e.signal_name, e.description, e.raw] for e in knowledge.configurations],
            ),
        ]

        if pack.all_compound_names:
            blocks.append(
                "### COMPOUND COMMANDS (callable as 'Compound <Name>')\n"
                + ", ".join(pack.all_compound_names)
            )
        if body_count:
            blocks.append(
                "### COMPOUND COMMAND BODIES (most relevant)\n"
                + "\n".join(_compound_body(c) for c in bodies[:body_count])
            )

        return "\n\n".join(b for b in blocks if b)

    counts = [len(io_opt), len(can_opt), len(cmd_opt), len(par_opt), len(mdl_opt), len(bodies)]
    rendered = build(*counts)

    # Shed the weakest evidence until the pack fits. Compound bodies go first, then the
    # tail of each fuzzy-matched list.
    while estimate_tokens(rendered) > budget_tokens and any(counts):
        for index in (5, 2, 1, 0, 4, 3):
            if counts[index] > 0:
                counts[index] -= 1
                break
        rendered = build(*counts)

    tokens = estimate_tokens(rendered)
    if tokens > budget_tokens:
        logger.warning(
            "[sys5] context for %s still %d tokens over budget after trimming; truncating",
            pack.requirement.requirement_id,
            tokens - budget_tokens,
        )
        rendered = truncate(rendered, int(budget_tokens * CHARS_PER_TOKEN))

    return rendered
