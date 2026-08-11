"""The Configurable_Parameters sheet.

Lists every Set/Verify target and tolerance actually referenced by this run's test
cases — never the whole project vocabulary — so the sheet stays a relevant reference for
these specific cases rather than a dump of everything the project happens to define.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from .....models import TestCase
from .....output.base import RenderContext
from .....output.styles import (
    BORDER,
    CENTER,
    TOP_LEFT,
    TOP_WRAP,
    set_widths,
    style_table_header_row,
)
from ._extract import used_names

_NAME_COL = 1
_DESCRIPTION_COL = 2
_FIRST_VARIANT_COL = 3


def write(worksheet: Worksheet, context: RenderContext, cases: list[TestCase]) -> None:
    names = used_names(cases, context.profile.allowed_verbs)
    variants = _variants_in_use(cases, context.available_variants)

    headers = ["Parameter Name", "Description", *variants]
    for column, header in enumerate(headers, start=1):
        worksheet.cell(row=1, column=column, value=header)
    style_table_header_row(worksheet, row=1, start_column=1, columns=len(headers))
    set_widths(worksheet, [26, 54, *([10] * len(variants))])

    if not names:
        worksheet.cell(row=2, column=1, value="No configurable parameters were used by this run.")
        return

    for offset, name in enumerate(names, start=1):
        row = 1 + offset
        _write_cell(worksheet, row, _NAME_COL, name, TOP_LEFT)
        _write_cell(worksheet, row, _DESCRIPTION_COL, context.describe(name), TOP_WRAP)
        for column_offset in range(len(variants)):
            # No per-variant value is tracked anywhere upstream (App Parameters and
            # tolerances are defined once, not per variant), so "-" is an honest
            # placeholder here rather than a value we would otherwise have to invent.
            _write_cell(worksheet, row, _FIRST_VARIANT_COL + column_offset, "-", CENTER)


def _write_cell(worksheet: Worksheet, row: int, column: int, value: str, alignment) -> None:
    cell = worksheet.cell(row=row, column=column, value=value)
    cell.alignment = alignment
    cell.border = BORDER


def _variants_in_use(cases: list[TestCase], canonical_order: tuple[str, ...]) -> list[str]:
    """Variant columns for this run only, ordered by the project's canonical list.

    A variant a case names that is outside the canonical list is still shown, just
    placed after the recognised ones — the column set describes what actually happened
    in the run, not what the project profile expected.
    """
    present = {case.variant for case in cases if case.variant}
    ordered = [v for v in canonical_order if v in present]
    ordered.extend(sorted(present.difference(canonical_order)))
    return ordered
