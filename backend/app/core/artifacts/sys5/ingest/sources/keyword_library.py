"""Parsers for the keyword-library workbook (*Library List*, *Keyword description*)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...models import LibraryFunction, Provenance
from ...utils.text import clean
from ..workbook import load_sheet

logger = logging.getLogger(__name__)

LIBRARY_HEADERS = ["SL.no", "Library", "Library Description"]
KEYWORD_HEADERS = ["SL.no", "Keywords", "Description", "Example", "Status"]

#: ``Lib_Ramp Signal_Name(Start=X,Stop=X,Step=X,Time=X)`` and friends. The optional
#: token between the function name and the parenthesis is a signal placeholder.
_SIGNATURE_RE = re.compile(
    r"^\s*(?P<fn>Lib_\w+)\s*(?P<signal>[A-Za-z_]\w*)?\s*\((?P<args>.*)\)\s*$",
    re.DOTALL,
)

#: Placeholder names that mean "a signal goes here", not a literal argument.
_SIGNAL_PLACEHOLDERS = {"signal_name", "signalname", "signal"}


def _parse_signature(text: str) -> tuple[str, list[str], bool] | None:
    """Split a library signature into (function name, parameter names, takes_signal).

    Handles both keyword arguments (``Start=X``) and positional ones
    (``Signal_1,Signal_2,Condition``). Returns ``None`` when the cell is not a signature.
    """
    match = _SIGNATURE_RE.match(clean(text))
    if not match:
        return None

    function = match.group("fn")
    signal = (match.group("signal") or "").lower()
    takes_signal = signal in _SIGNAL_PLACEHOLDERS or bool(signal)

    parameters: list[str] = []
    for raw in match.group("args").split(","):
        argument = clean(raw)
        if not argument:
            continue
        parameters.append(clean(argument.split("=", 1)[0]))

    return function, parameters, takes_signal


def parse_library_list(path: Path, sheet: str) -> list[LibraryFunction]:
    """Read the declared ``Lib_*`` functions.

    A generated step may only call a library whose signature appears here, and only with
    the parameter names declared in that signature.
    """
    table = load_sheet(path, sheet, LIBRARY_HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    functions: list[LibraryFunction] = []
    for row in table.rows:
        signature = row.get("Library", "Library Name", "Libraries")
        if not signature:
            continue
        parsed = _parse_signature(signature)
        if parsed is None:
            logger.debug("[sys5] skipping unparseable library signature: %r", signature)
            continue

        function, parameters, takes_signal = parsed
        functions.append(
            LibraryFunction(
                name=function,
                signature=signature,
                parameters=parameters,
                takes_signal=takes_signal,
                description=row.get("Library Description", "Description"),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d library functions", path.name, sheet, len(functions))
    return functions


def parse_keyword_description(path: Path, sheet: str) -> list[str]:
    """Read the declared keyword names (``Set <Signal_Name>``, ``Wait``, ``Compound ...``).

    Informational: the grammar's allowed verbs come from the project profile. This is
    parsed so a run can log a warning when the profile and the workbook disagree.
    """
    table = load_sheet(path, sheet, KEYWORD_HEADERS)
    if not table:
        return []

    keywords: list[str] = []
    for row in table.rows:
        keyword = row.get("Keywords", "Keyword")
        if keyword:
            keywords.append(keyword)

    logger.debug("[sys5] %s[%s]: declared keywords %s", path.name, sheet, keywords)
    return keywords
