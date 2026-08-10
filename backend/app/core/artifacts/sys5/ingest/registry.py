"""Classification of input sheets by fingerprint rather than filename.

Which supporting workbooks accompany a requirements file differs per project and per
iteration, and the filenames are not stable. So every sheet of every workbook found in
the input directory is probed: if its name or its header row matches a known
:class:`SourceKind` fingerprint, it is parsed by the matching source parser; if it
matches nothing it is logged and skipped, never guessed at.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

from ..utils.text import clean, feature_key, normalize
from .workbook import find_header_row, read_grid, sheet_names

logger = logging.getLogger(__name__)


class SourceKind(StrEnum):
    """The kinds of input sheet the pipeline knows how to read."""

    REQUIREMENTS = "requirements"
    COMM_MATRIX = "comm_matrix"
    IO_SIGNALS = "io_signals"
    APP_PARAMETERS = "app_parameters"
    COMMAND_LIST = "command_list"
    COMPOUND_SET = "compound_set"
    COMPOUND_VERIFY = "compound_verify"
    KEYWORD_DESCRIPTION = "keyword_description"
    LIBRARY_LIST = "library_list"
    TOLERANCES = "tolerances"
    CONFIGURATIONS = "configurations"
    MODEL_INPUT_MAPPING = "model_input_mapping"
    GLOBAL_VARIABLES = "global_variables"


#: Sheets that are decoration or human-only reference material.
IGNORED_SHEET_PATTERNS = (
    "coverpage",
    "cover",
    "index",
    "help",
    "revisionhistory",
    "masterlistabbreviations",
    "abbreviations",
    "truckmodelinfo",
    "verificationlogics",
)

_FEATURE_SHEET_RE = re.compile(r"^\s*0*\d{1,3}\s*$")


@dataclass(frozen=True, slots=True)
class SheetFingerprint:
    """How to recognise one kind of sheet."""

    kind: SourceKind
    #: Normalised sheet names that identify this kind outright.
    names: tuple[str, ...] = ()
    #: Header names expected in the table; used both for detection and header-row finding.
    headers: tuple[str, ...] = ()
    #: How many of ``headers`` must be present for a header-based match.
    min_headers: int = 2
    #: Headers that must all be present for a match (discriminates similar sheets).
    required: tuple[str, ...] = ()

    def name_matches(self, sheet: str) -> bool:
        target = normalize(sheet)
        return any(normalize(n) == target for n in self.names)


#: The TMHC fingerprints. A new project adds entries here, not code elsewhere.
FINGERPRINTS: tuple[SheetFingerprint, ...] = (
    SheetFingerprint(
        kind=SourceKind.REQUIREMENTS,
        headers=(
            "Requirement ID",
            "Object Heading",
            "Object Text",
            "Category",
            "Variant",
            "Priority",
            "Verification Method",
            "Verification Stage",
            "Verification Criteria",
            "Source",
            "Status",
        ),
        required=("Requirement ID", "Object Text"),
        min_headers=3,
    ),
    SheetFingerprint(
        kind=SourceKind.COMM_MATRIX,
        names=("Master Comm Matrix (CAN)", "Master Comm Matrix", "Comm Matrix"),
        headers=(
            "Signal ID",
            "Message Name",
            "Message IDs",
            "Logical Signal Name",
            "Signal Name",
            "Signal Description",
        ),
        required=("Signal ID", "Message Name"),
        min_headers=3,
    ),
    SheetFingerprint(
        kind=SourceKind.IO_SIGNALS,
        names=("Master Input Output Signals", "Input Output Signals"),
        headers=("Signal ID", "Logical Signal Name", "Signal Type"),
        required=("Signal ID", "Signal Type"),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.APP_PARAMETERS,
        names=("Master List - App Parameter", "App Parameter", "Master List App Parameter"),
        headers=(
            "Parameter ID",
            "Parameter Name",
            "Parameter Description(purpose)",
            "Parameter Type",
            "Parameter default value",
            "Parameter min Value",
            "Parameter max Value",
        ),
        required=("Parameter ID", "Parameter Name"),
        min_headers=3,
    ),
    SheetFingerprint(
        kind=SourceKind.COMMAND_LIST,
        names=("Command List", "Command_List", "Command_List_Diagnostics"),
        headers=(
            "SL.No",
            "Type",
            "Command name",
            "Message Name",
            "Signal Description",
            "Signal Name",
        ),
        required=("Command name", "Signal Name"),
        min_headers=3,
    ),
    SheetFingerprint(
        kind=SourceKind.COMPOUND_SET,
        names=("Compound Commands (Set)", "Compound Commands Set", "Compound Commands"),
    ),
    SheetFingerprint(
        kind=SourceKind.COMPOUND_VERIFY,
        names=("Compound Command (Verify)", "Compound Commands (Verify)"),
    ),
    SheetFingerprint(
        kind=SourceKind.KEYWORD_DESCRIPTION,
        names=("Keyword description", "Keyword Description"),
        headers=("SL.no", "Keywords", "Description", "Example", "Status"),
        required=("Keywords",),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.LIBRARY_LIST,
        names=("Library List", "Library_List"),
        headers=("SL.no", "Library", "Library Description"),
        required=("Library",),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.TOLERANCES,
        names=("Tolerances", "Tolerance"),
        headers=(
            "Sl No",
            "Tolerance Configuration",
            "Description",
            "Example",
            "Unit",
            "Value",
            "Tolerance Unit",
        ),
        required=("Tolerance Configuration",),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.CONFIGURATIONS,
        names=("Configurations", "Configuration"),
        headers=("Sl No", "Signal Name", "Signal Description", "Configuration"),
        required=("Signal Name", "Configuration"),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.MODEL_INPUT_MAPPING,
        names=("Model_Input_Mapping", "Model Input Mapping"),
        headers=("Sl.No.", "Signal", "Test Case Input", "Model Input", "Model Output to ECU"),
        required=("Signal", "Test Case Input"),
        min_headers=2,
    ),
    SheetFingerprint(
        kind=SourceKind.GLOBAL_VARIABLES,
        names=("Global_Variables", "Global Variables"),
    ),
)


@dataclass(slots=True)
class ClassifiedSheet:
    """One sheet, resolved to a kind."""

    path: Path
    sheet: str
    kind: SourceKind
    #: Set when the sheet is a per-feature requirement sheet (``"5"`` for sheet ``005``).
    feature: str = ""

    @property
    def label(self) -> str:
        return f"{self.path.name}[{self.sheet}]"


@dataclass(slots=True)
class InputInventory:
    """Everything the pipeline found in the input directory."""

    sheets: list[ClassifiedSheet] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    def of_kind(self, *kinds: SourceKind) -> list[ClassifiedSheet]:
        wanted = set(kinds)
        return [s for s in self.sheets if s.kind in wanted]

    def requirement_sheets(self) -> list[ClassifiedSheet]:
        return self.of_kind(SourceKind.REQUIREMENTS)

    def feature_keys(self) -> list[str]:
        """Feature keys of every requirement sheet, in sheet order."""
        return [s.feature for s in self.requirement_sheets() if s.feature]


def _is_ignored(sheet: str) -> bool:
    target = normalize(sheet)
    return any(pattern in target for pattern in IGNORED_SHEET_PATTERNS)


def _headers_of(path: Path, sheet: str, fingerprint: SheetFingerprint) -> set[str]:
    """Normalised header names of a sheet, detected with a fingerprint's hints."""
    grid = read_grid(path, sheet)
    if not grid:
        return set()
    index = find_header_row(grid, list(fingerprint.headers))
    if index < 0:
        return set()
    return {normalize(c) for c in grid[index] if clean(c)}


def classify_sheet(path: Path, sheet: str) -> SourceKind | None:
    """Resolve one sheet to a :class:`SourceKind`, or ``None`` if unrecognised.

    Name matches win outright; otherwise the sheet's header row is compared against each
    fingerprint and the highest-scoring match above its threshold is taken.
    """
    for fingerprint in FINGERPRINTS:
        if fingerprint.name_matches(sheet):
            return fingerprint.kind

    if _is_ignored(sheet):
        return None

    best: tuple[int, SourceKind] | None = None
    for fingerprint in FINGERPRINTS:
        if not fingerprint.headers:
            continue
        headers = _headers_of(path, sheet, fingerprint)
        if not headers:
            continue
        if not all(normalize(r) in headers for r in fingerprint.required):
            continue
        score = sum(1 for h in fingerprint.headers if normalize(h) in headers)
        if score >= fingerprint.min_headers and (best is None or score > best[0]):
            best = (score, fingerprint.kind)

    return best[1] if best else None


def build_inventory(paths: list[Path], req_filename: str = "") -> InputInventory:
    """Classify every sheet of every workbook.

    ``req_filename`` is an optional hint: when given, only that workbook is searched for
    requirement sheets, which prevents a stray copy in the input directory from being
    picked up as a second source of requirements.
    """
    inventory = InputInventory()
    req_hint = normalize(req_filename) if req_filename else ""

    for path in paths:
        try:
            names = sheet_names(path)
        except Exception as exc:  # noqa: BLE001 - a bad workbook must not kill the run
            logger.warning("[sys5] cannot open %s: %s", path.name, exc)
            inventory.skipped.append(f"{path.name} (unreadable: {exc})")
            continue

        is_req_file = not req_hint or normalize(path.name) == req_hint

        for sheet in names:
            kind = classify_sheet(path, sheet)
            if kind is None:
                inventory.skipped.append(f"{path.name}[{sheet}]")
                continue

            if kind is SourceKind.REQUIREMENTS:
                if not is_req_file:
                    inventory.skipped.append(f"{path.name}[{sheet}] (not the requirements file)")
                    continue
                feature = feature_key(sheet) if _FEATURE_SHEET_RE.match(sheet) else ""
                inventory.sheets.append(
                    ClassifiedSheet(path=path, sheet=sheet, kind=kind, feature=feature)
                )
                continue

            inventory.sheets.append(ClassifiedSheet(path=path, sheet=sheet, kind=kind))

    logger.info(
        "[sys5] inventory: %d sheets classified, %d skipped",
        len(inventory.sheets),
        len(inventory.skipped),
    )
    for sheet in inventory.sheets:
        logger.debug("[sys5]   %s -> %s", sheet.label, sheet.kind)
    if inventory.skipped:
        logger.debug("[sys5]   skipped: %s", ", ".join(inventory.skipped))
    return inventory
