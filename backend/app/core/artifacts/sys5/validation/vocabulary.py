"""Vocabulary enforcement — the anti-hallucination check.

Every name a step references must exist in the :class:`VocabularyIndex` built from the
input workbooks. There is no fuzzy acceptance here: a name is in the sheets or the step
is rejected. Suggestions are attached to failures so the repair round has somewhere to
go, but a suggestion is never applied automatically.
"""

from __future__ import annotations

from ..indexing import VocabularyIndex
from ..models import LibraryFunction, TestCase, ValidationIssue, VocabKind
from ..projects import ProjectProfile
from ..utils.text import normalize
from .grammar import ParsedStep, StepKind, parse_all

#: Kinds a ``Set`` or ``Verify`` target may resolve to.
_ADDRESSABLE = {
    VocabKind.IO_SIGNAL,
    VocabKind.CAN_SIGNAL,
    VocabKind.COMMAND,
    VocabKind.MODEL_SIGNAL,
    VocabKind.APP_PARAMETER,
    VocabKind.GLOBAL_VARIABLE,
}


def check_vocabulary(
    case: TestCase,
    index: VocabularyIndex,
    profile: ProjectProfile,
    scoped_names: set[str] | None = None,
) -> tuple[list[ValidationIssue], list[ParsedStep]]:
    """Validate grammar and name legality together.

    ``scoped_names`` is the set of names traced to this specific requirement (the same
    list rendered into the generator/repair prompts as the "legal names" the model was
    told to use) — normalized here, so callers may pass names in any casing/spelling.
    When given, a ``Set``/``Verify`` target that is legal *somewhere* in the project but
    was not traced to this requirement is flagged too — a name being real is not the
    same as it being the right one for this test case.

    Returns the issues plus the parsed steps, so callers that also need the parse (the
    semantic checks) do not repeat the work.
    """
    issues: list[ValidationIssue] = []
    parsed = parse_all(case.steps, profile.allowed_verbs)
    # Normalized -> original spelling, so a suggestion can show a real name rather than
    # its stripped-down comparison key.
    scope = (
        {normalize(n): n for n in scoped_names if normalize(n)}
        if scoped_names is not None
        else None
    )

    for step, node in zip(case.steps, parsed, strict=True):
        if node.kind is StepKind.INVALID:
            issues.append(
                ValidationIssue(
                    code="BAD_GRAMMAR",
                    step_no=step.step_no,
                    message=node.error or f"unparseable step {node.raw!r}",
                    suggestion=(
                        "use Set <name>, Wait, Verify <name>, Lib_<Function>(...) or "
                        "Compound <Name>"
                    ),
                )
            )
            continue

        match node.kind:
            case StepKind.SET | StepKind.VERIFY:
                issues.extend(_check_target(step.step_no, node, index, scope))
            case StepKind.COMPOUND:
                issues.extend(_check_compound(step.step_no, node, index, profile))
            case StepKind.LIBRARY:
                issues.extend(_check_library(step.step_no, node, index, profile))
            case _:
                pass

    return issues, parsed


def _suggest_within(target: str, scope: dict[str, str], limit: int = 3) -> list[str]:
    """Nearest *display* names to ``target`` drawn only from ``scope`` (normalized -> original).

    Used when a name is legal in the project but out of scope for this requirement, so
    the repair round is pointed at a name it may actually use, not just any real one.
    """
    target_norm = normalize(target)
    if not target_norm:
        return []
    substring = [
        display for key, display in scope.items() if target_norm in key or key in target_norm
    ]
    if substring:
        return substring[:limit]
    from rapidfuzz import fuzz, process

    matches = process.extract(target_norm, list(scope.keys()), scorer=fuzz.WRatio, limit=limit)
    return [scope[key] for key, score, _ in matches if score >= 70]


def _check_target(
    step_no: int, node: ParsedStep, index: VocabularyIndex, scoped_names: dict[str, str] | None
) -> list[ValidationIssue]:
    entry = index.resolve(node.target)
    if entry is None:
        suggestions = index.suggest(node.target)
        return [
            ValidationIssue(
                code="UNKNOWN_NAME",
                step_no=step_no,
                message=(
                    f"{node.target!r} does not appear in any input sheet and may not be used"
                ),
                suggestion=(
                    f"use one of: {', '.join(suggestions)}"
                    if suggestions
                    else "use a name from the provided signal/command list"
                ),
            )
        ]

    if not (entry.kinds & _ADDRESSABLE):
        kinds = ", ".join(sorted(k.value for k in entry.kinds))
        return [
            ValidationIssue(
                code="WRONG_NAME_KIND",
                step_no=step_no,
                message=f"{node.target!r} is a {kinds}, which cannot be a {node.verb} target",
                suggestion="reference a signal, command or parameter instead",
            )
        ]

    if scoped_names is not None and normalize(node.target) not in scoped_names:
        suggestions = _suggest_within(node.target, scoped_names)
        return [
            ValidationIssue(
                code="OUT_OF_SCOPE_NAME",
                step_no=step_no,
                message=(
                    f"{node.target!r} is a real name but was not traced to this "
                    "requirement — it belongs elsewhere"
                ),
                suggestion=(
                    f"use one of: {', '.join(suggestions)}"
                    if suggestions
                    else "use a name from this requirement's own reference data"
                ),
            )
        ]

    return []


def _check_compound(
    step_no: int, node: ParsedStep, index: VocabularyIndex, profile: ProjectProfile
) -> list[ValidationIssue]:
    if not profile.allow_compound_calls:
        return [
            ValidationIssue(
                code="COMPOUND_NOT_ALLOWED",
                step_no=step_no,
                message="compound commands are disabled for this project",
                suggestion="expand the compound into primitive Set/Wait/Verify steps",
            )
        ]

    if index.is_legal(node.target, {VocabKind.COMPOUND}):
        return []

    suggestions = [
        record.name
        for record in index.of_kind(VocabKind.COMPOUND)
        if node.target.lower() in record.name.lower()
    ][:3] or index.suggest(node.target)
    return [
        ValidationIssue(
            code="UNKNOWN_COMPOUND",
            step_no=step_no,
            message=f"no compound command named {node.target!r} exists in the input sheets",
            suggestion=(
                f"use one of: {', '.join(suggestions)}"
                if suggestions
                else "use a compound listed in the compound-commands sheet"
            ),
        )
    ]


def _check_library(
    step_no: int, node: ParsedStep, index: VocabularyIndex, profile: ProjectProfile
) -> list[ValidationIssue]:
    if not profile.allow_library_calls:
        return [
            ValidationIssue(
                code="LIBRARY_NOT_ALLOWED",
                step_no=step_no,
                message="library functions are disabled for this project",
                suggestion="express the behaviour with primitive Set/Wait/Verify steps",
            )
        ]

    entry = index.resolve(node.verb)
    library = next(
        (r for r in (entry.records if entry else []) if isinstance(r, LibraryFunction)), None
    )
    if library is None:
        available = [r.name for r in index.of_kind(VocabKind.LIBRARY)]
        return [
            ValidationIssue(
                code="UNKNOWN_LIBRARY",
                step_no=step_no,
                message=f"no library function named {node.verb!r} is declared",
                suggestion=(
                    f"use one of: {', '.join(available)}" if available else "do not call libraries"
                ),
            )
        ]

    issues: list[ValidationIssue] = []

    # The signal a library operates on must itself be a legal name.
    if node.target and not index.is_legal(node.target, _ADDRESSABLE):
        suggestions = index.suggest(node.target)
        issues.append(
            ValidationIssue(
                code="UNKNOWN_NAME",
                step_no=step_no,
                message=f"{node.target!r} in {node.verb} does not appear in any input sheet",
                suggestion=(
                    f"use one of: {', '.join(suggestions)}" if suggestions else "use a listed signal"
                ),
            )
        )

    declared = {p.lower() for p in library.parameters}
    if node.arguments:
        supplied = {k.lower() for k in node.arguments}
        if unknown := supplied - declared:
            issues.append(
                ValidationIssue(
                    code="BAD_LIBRARY_ARGS",
                    step_no=step_no,
                    message=(
                        f"{node.verb} does not accept {', '.join(sorted(unknown))}; "
                        f"its signature is {library.signature}"
                    ),
                    suggestion=f"use exactly: {', '.join(library.parameters)}",
                )
            )
        if missing := declared - supplied:
            issues.append(
                ValidationIssue(
                    code="BAD_LIBRARY_ARGS",
                    step_no=step_no,
                    message=(
                        f"{node.verb} is missing {', '.join(sorted(missing))}; "
                        f"its signature is {library.signature}"
                    ),
                    suggestion=f"supply every parameter: {', '.join(library.parameters)}",
                )
            )
    elif node.positional and len(node.positional) != len(library.parameters):
        issues.append(
            ValidationIssue(
                code="BAD_LIBRARY_ARGS",
                step_no=step_no,
                message=(
                    f"{node.verb} takes {len(library.parameters)} arguments "
                    f"({', '.join(library.parameters)}), got {len(node.positional)}"
                ),
                suggestion=f"match the declared signature: {library.signature}",
            )
        )

    return issues
