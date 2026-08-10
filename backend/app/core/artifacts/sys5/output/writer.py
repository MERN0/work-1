"""The template-agnostic workbook writer.

Consumes an :class:`OutputTemplate`'s column and sheet specs and its emitted rows. All
the openpyxl mechanics — merging, banding, widths, freezing — live here, so a new
template declares a layout rather than reimplementing spreadsheet plumbing.
"""

from __future__ import annotations

import logging
from pathlib import Path

from openpyxl import Workbook
from openpyxl.worksheet.worksheet import Worksheet

from ..models import TestCase
from ..utils.text import sheet_safe
from .base import ColumnSpec, OutputTemplate, RenderContext, RenderResult, Row
from .styles import (
    BORDER,
    CENTER_TOP,
    PHASE_FILLS,
    TOP_LEFT,
    TOP_WRAP,
    freeze_and_filter,
    set_widths,
    style_header_row,
)

logger = logging.getLogger(__name__)

HEADER_ROW = 1


def render_workbook(
    template: OutputTemplate,
    cases: list[TestCase],
    context: RenderContext,
    destination: Path,
) -> RenderResult:
    """Render ``cases`` into a workbook at ``destination``."""
    workbook = Workbook()
    # Drop the default sheet; every tab comes from the template's specs.
    workbook.remove(workbook.active)

    columns = template.columns()
    rows: list[Row] = []

    for spec in template.sheets():
        name = sheet_safe(template.sheet_name(spec, context))
        worksheet = workbook.create_sheet(title=name)

        if template.write_sheet(spec, worksheet, context):
            continue

        rows = list(template.emit_rows(cases, context))
        _write_test_cases(worksheet, columns, rows)

    _apply_properties(workbook, template, context)

    destination.parent.mkdir(parents=True, exist_ok=True)
    workbook.save(destination)

    logger.info(
        "[sys5] wrote %s (%d test cases, %d rows, template=%s)",
        destination.name,
        len(cases),
        len(rows),
        template.name,
    )
    return RenderResult(path=destination, rows=len(rows), cases=len(cases))


def _write_test_cases(worksheet: Worksheet, columns: list[ColumnSpec], rows: list[Row]) -> None:
    """Write the header, the data rows, then the merges and banding."""
    for index, column in enumerate(columns, start=1):
        worksheet.cell(row=HEADER_ROW, column=index, value=column.header)
    style_header_row(worksheet, HEADER_ROW, len(columns))
    set_widths(worksheet, [c.width for c in columns])

    for offset, row in enumerate(rows):
        excel_row = HEADER_ROW + 1 + offset
        if row.blank:
            continue

        fill = PHASE_FILLS.get(row.phase)
        for index, column in enumerate(columns, start=1):
            cell = worksheet.cell(row=excel_row, column=index, value=row.values.get(column.key, ""))
            cell.alignment = TOP_WRAP if column.wrap else TOP_LEFT
            cell.border = BORDER
            if fill is not None:
                cell.fill = fill

    _apply_merges(worksheet, columns, rows)
    freeze_and_filter(worksheet, HEADER_ROW, len(columns), len(rows))


def _apply_merges(worksheet: Worksheet, columns: list[ColumnSpec], rows: list[Row]) -> None:
    """Merge the metadata columns down each test case, and the phase column per block.

    Merging is what makes the sheet readable: without it the test-case id and
    description repeat on every one of a case's thirty-odd rows.
    """
    for index, column in enumerate(columns, start=1):
        if column.merge_per_case:
            _merge_runs(worksheet, index, rows, key=lambda r: r.case_index)
        elif column.merge_per_phase:
            _merge_runs(worksheet, index, rows, key=lambda r: (r.case_index, r.phase))


def _merge_runs(worksheet: Worksheet, column: int, rows: list[Row], key) -> None:
    """Merge each maximal run of consecutive rows sharing ``key(row)``."""
    start: int | None = None
    current = None

    for offset, row in enumerate(rows):
        excel_row = HEADER_ROW + 1 + offset
        value = None if row.blank else key(row)

        if value != current:
            _close_run(worksheet, column, start, excel_row - 1)
            start = None if row.blank else excel_row
            current = value

    _close_run(worksheet, column, start, HEADER_ROW + len(rows))


def _close_run(worksheet: Worksheet, column: int, start: int | None, end: int) -> None:
    if start is not None and end > start:
        worksheet.merge_cells(
            start_row=start, start_column=column, end_row=end, end_column=column
        )
        worksheet.cell(row=start, column=column).alignment = CENTER_TOP


def _apply_properties(workbook: Workbook, template: OutputTemplate, context: RenderContext) -> None:
    properties = template.document_properties(context)
    workbook.properties.title = properties.get("title", context.title)
    workbook.properties.creator = properties.get("creator", "SYS5 AI Pipeline")
    workbook.properties.description = properties.get("description", "")
