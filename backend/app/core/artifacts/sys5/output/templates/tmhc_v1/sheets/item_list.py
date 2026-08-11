"""The Item_List sheet: one row per generated test case, for a quick scan of the run.

Every value is read straight off the corresponding test case — nothing here is
recomputed or re-decided, so this sheet can never disagree with the test-case sheet it
summarises.
"""

from __future__ import annotations

from openpyxl.worksheet.worksheet import Worksheet

from .....models import TestCase
from .....output.base import RenderContext
from .....output.styles import BORDER, TOP_LEFT, TOP_WRAP, set_widths, style_table_header_row

_HEADERS = [
    "Sl.No",
    "Test Type",
    "Feature Name",
    "Test Case ID",
    "Applicable Variants",
    "Execution Required",
    "Remarks",
]
_WIDTHS = [7, 16, 34, 18, 16, 15, 42]
_WRAP_COLUMNS = {3, 7}


def write(worksheet: Worksheet, context: RenderContext, cases: list[TestCase]) -> None:
    for column, header in enumerate(_HEADERS, start=1):
        worksheet.cell(row=1, column=column, value=header)
    style_table_header_row(worksheet, row=1, start_column=1, columns=len(_HEADERS))
    set_widths(worksheet, _WIDTHS)

    if not cases:
        worksheet.cell(row=2, column=1, value="No test cases were generated for this run.")
        return

    for offset, case in enumerate(cases, start=1):
        row = 1 + offset
        values = [
            str(offset),
            case.test_type or "Normal_System",
            case.aspect or case.description,
            case.tc_id,
            case.variant,
            context.profile.execute_value,
            _remark(case),
        ]
        for column, value in enumerate(values, start=1):
            cell = worksheet.cell(row=row, column=column, value=value)
            cell.alignment = TOP_WRAP if column in _WRAP_COLUMNS else TOP_LEFT
            cell.border = BORDER


def _remark(case: TestCase) -> str:
    """A one-line pointer to the detailed issues on the test-case sheet, not a copy of them."""
    if not case.issues:
        return ""
    codes = ", ".join(sorted({issue.code for issue in case.issues}))
    return f"Needs review: {codes}"
