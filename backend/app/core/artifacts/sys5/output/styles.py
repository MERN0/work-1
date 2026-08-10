"""Shared openpyxl styling so every template produces a workbook that looks deliberate."""

from __future__ import annotations

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

HEADER_FILL = PatternFill("solid", fgColor="4472C4")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)

TITLE_FONT = Font(bold=True, size=14)
LABEL_FONT = Font(bold=True, size=11)

TABLE_HEADER_FILL = PatternFill("solid", fgColor="D9E2F3")
TABLE_HEADER_FONT = Font(bold=True, size=11)

#: Soft banding per phase so a reader can see the three parts of a case at a glance.
PHASE_FILLS = {
    "PRECONDITION": PatternFill("solid", fgColor="EDF3FB"),
    "ACTION": PatternFill("solid", fgColor="FFFFFF"),
    "POSTCONDITION": PatternFill("solid", fgColor="F4F0FA"),
}

_SIDE = Side(style="thin", color="BFBFBF")
BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)

TOP_WRAP = Alignment(vertical="top", wrap_text=True)
TOP_LEFT = Alignment(vertical="top", horizontal="left")
CENTER = Alignment(vertical="center", horizontal="center", wrap_text=True)
CENTER_TOP = Alignment(vertical="top", horizontal="center", wrap_text=True)

#: Marks a sheet whose real layout has not been supplied yet.
STUB_FONT = Font(italic=True, color="808080", size=10)


def style_header_row(worksheet: Worksheet, row: int, columns: int) -> None:
    """Apply the header look to one row."""
    for index in range(1, columns + 1):
        cell = worksheet.cell(row=row, column=index)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER


def set_widths(worksheet: Worksheet, widths: list[int]) -> None:
    """Set column widths from a positional list."""
    for index, width in enumerate(widths, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width


def freeze_and_filter(worksheet: Worksheet, header_row: int, columns: int, rows: int) -> None:
    """Freeze the header and add an autofilter over the data."""
    worksheet.freeze_panes = worksheet.cell(row=header_row + 1, column=1)
    if rows > 0:
        last = get_column_letter(columns)
        worksheet.auto_filter.ref = f"A{header_row}:{last}{header_row + rows}"


def write_stub(worksheet: Worksheet, title: str, note: str) -> None:
    """Render a placeholder sheet.

    Used for the auxiliary sheets whose real structure has not been provided yet. The
    tab exists in the right position with the right name so the workbook is complete,
    and the note says plainly that the layout is pending rather than leaving a reader to
    guess whether the sheet failed to generate.
    """
    worksheet["A1"] = title
    worksheet["A1"].font = TITLE_FONT
    worksheet["A3"] = note
    worksheet["A3"].font = STUB_FONT
    worksheet.column_dimensions["A"].width = 120
