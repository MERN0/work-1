"""Parser for a SYS2 requirement (feature) sheet."""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import FeatureContext, FeatureIdentity, Provenance, RequirementRow
from ...utils.text import clean, normalize
from ..workbook import SheetTable, load_sheet

logger = logging.getLogger(__name__)

REQUIREMENT_HEADERS = [
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
    "Release",
    "Downstream Traceability",
    "Remarks",
]

#: ``Object Heading`` values that identify the feature itself.
_GROUP_HEADINGS = ("feature group", "featuregroup")
_NAME_HEADINGS = ("feature name", "featurename")

#: Context headings worth carrying into the prompt, in the order they should appear.
_CONTEXT_PRIORITY = ("purpose", "overview", "featuredetails", "contextdiagram", "description")


def load_requirement_sheet(path: Path, sheet: str) -> SheetTable:
    """Load a feature sheet with requirement header hints."""
    return load_sheet(path, sheet, REQUIREMENT_HEADERS)


def parse_rows(table: SheetTable) -> list[RequirementRow]:
    """Turn a loaded feature sheet into raw requirement rows.

    Every cell is preserved in ``cells`` so keyword selection can scan columns that are
    not part of the known schema.
    """
    rows: list[RequirementRow] = []
    for row in table.rows:
        rows.append(
            RequirementRow(
                requirement_id=row.get("Requirement ID", "RequirementID", "Req ID"),
                object_heading=row.get("Object Heading", "ObjectHeading"),
                object_text=row.get("Object Text", "ObjectText"),
                category=row.get("Category"),
                variant=row.get("Variant"),
                priority=row.get("Priority"),
                verification_method=row.get("Verification Method"),
                verification_stage=row.get("Verification Stage"),
                verification_criteria=row.get("Verification Criteria"),
                source=row.get("Source"),
                status=row.get("Status"),
                remarks=row.get("Remarks", "Remark"),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
                cells=row.non_empty(),
            )
        )
    return rows


def parse_feature_identity(table: SheetTable, rows: list[RequirementRow]) -> FeatureIdentity:
    """Read Feature Group / Feature Name from the sheet's heading rows.

    These sit near the top of every feature sheet as ``Object Heading`` labels with the
    value in ``Object Text``. They are constant for the sheet and drive the cover title,
    the ``Feature`` column and the workbook metadata.
    """
    group = name = ""
    for row in rows:
        heading = normalize(row.object_heading)
        if not heading:
            continue
        if not group and heading in _GROUP_HEADINGS:
            group = row.object_text
        elif not name and heading in _NAME_HEADINGS:
            name = row.object_text
        if group and name:
            break

    identity = FeatureIdentity(sheet=table.sheet, group=group, name=name)
    if not (group or name):
        logger.warning(
            "[sys5] %s[%s]: no Feature Group/Name rows found; falling back to the sheet name",
            table.file,
            table.sheet,
        )
    return identity


def parse_feature_context(
    table: SheetTable, rows: list[RequirementRow], identity: FeatureIdentity
) -> FeatureContext:
    """Collect the Heading/Information rows that describe the feature as a whole.

    Purpose, Overview and similar rows are not requirements but they are what makes an
    isolated requirement sentence intelligible, so they are attached to every
    requirement of the sheet.
    """
    sections: list[tuple[str, str]] = []
    for row in rows:
        if not row.is_context_row():
            continue
        heading = clean(row.object_heading)
        text = clean(row.object_text)
        if not text or normalize(heading) in (*_GROUP_HEADINGS, *_NAME_HEADINGS):
            continue
        sections.append((heading or "Information", text))

    def rank(item: tuple[str, str]) -> int:
        key = normalize(item[0])
        return _CONTEXT_PRIORITY.index(key) if key in _CONTEXT_PRIORITY else len(_CONTEXT_PRIORITY)

    sections.sort(key=rank)
    return FeatureContext(identity=identity, sections=sections, notes=list(table.notes))


def parse_requirement_sheet(
    path: Path, sheet: str
) -> tuple[FeatureIdentity, FeatureContext, list[RequirementRow]]:
    """Parse a feature sheet into its identity, context and raw rows."""
    table = load_requirement_sheet(path, sheet)
    rows = parse_rows(table)
    identity = parse_feature_identity(table, rows)
    context = parse_feature_context(table, rows, identity)
    logger.info(
        "[sys5] %s[%s]: %d rows, feature=%r",
        path.name,
        sheet,
        len(rows),
        identity.title,
    )
    return identity, context, rows
