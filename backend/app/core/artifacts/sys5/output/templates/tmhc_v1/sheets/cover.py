"""The Cover sheet of the TMHC output workbook.

The title is the **feature name taken from the requirement sheet** — for feature 005
that is ``005 - Ramp / Slope Control`` — so a workbook identifies the feature it covers
without a reader having to open the test-case tab.
"""

from __future__ import annotations

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from ....base import RenderContext
from ....styles import (
    BORDER,
    CENTER,
    LABEL_FONT,
    TABLE_HEADER_FILL,
    TABLE_HEADER_FONT,
    TITLE_FONT,
    TOP_WRAP,
)

#: Column widths A..H.
_WIDTHS = [4, 12, 26, 16, 20, 20, 14, 46]

_REVISION_HEADERS = [
    "Revision No:",
    "Change Description",
    "Date",
    "Created by",
    "Approved by",
    "Description",
]

AUTHOR = "SYS5 AI Pipeline"


def write(worksheet: Worksheet, context: RenderContext) -> None:
    """Render the cover page."""
    for index, width in enumerate(_WIDTHS, start=1):
        worksheet.column_dimensions[get_column_letter(index)].width = width

    # Title — the feature name from the requirements.
    worksheet["C3"] = context.title
    worksheet["C3"].font = TITLE_FONT
    worksheet["C3"].alignment = TOP_WRAP

    document_no = f"{context.project_name.upper()}/SYS5/{context.sheet}"
    metadata = [
        ("Document No.", document_no),
        ("Version", context.version),
        ("Created By:", AUTHOR),
        ("Verified By:", AUTHOR),
    ]
    for offset, (label, value) in enumerate(metadata):
        row = 6 + offset
        worksheet.cell(row=row, column=5, value=label).font = LABEL_FONT
        worksheet.cell(row=row, column=6, value=value)

    worksheet["E11"] = "Revision History"
    worksheet["E11"].font = LABEL_FONT

    header_row = 12
    for offset, header in enumerate(_REVISION_HEADERS):
        cell = worksheet.cell(row=header_row, column=3 + offset, value=header)
        cell.fill = TABLE_HEADER_FILL
        cell.font = TABLE_HEADER_FONT
        cell.alignment = CENTER
        cell.border = BORDER

    revision = [
        "1.0",
        f"Auto-generated for {context.project_name}",
        context.generated_at.strftime("%Y-%m-%d"),
        AUTHOR,
        AUTHOR,
        f"{context.title} — {context.summary.test_cases_generated} test case(s) "
        f"from {context.summary.requirements_selected} requirement(s)",
    ]
    for offset, value in enumerate(revision):
        cell = worksheet.cell(row=header_row + 1, column=3 + offset, value=value)
        cell.alignment = TOP_WRAP
        cell.border = BORDER
