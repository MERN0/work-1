"""The Test Pattern sheet: which ``Set`` parameters this run varied, and how.

Derived entirely from the rendered steps: a factor appears here only because a test case
actually set it, its listed elements are only the values actually used (never the full
range a parameter could theoretically take), and "Fixed" vs "Variable" is a mechanical
fact about the run — the value was the same in every case that touched it, or it wasn't.
"""

from __future__ import annotations

from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .....models import TestCase
from .....output.base import RenderContext
from .....output.styles import (
    BORDER,
    CENTER,
    LABEL_FONT,
    TOP_LEFT,
    TOP_WRAP,
    style_table_header_row,
)
from ._extract import set_factor_matrix

_NO_VALUE = "No test case set a configurable value for this run."


def write(worksheet: Worksheet, context: RenderContext, cases: list[TestCase]) -> None:
    factors = set_factor_matrix(cases, context.profile.allowed_verbs)

    worksheet.column_dimensions["A"].width = 28
    worksheet.column_dimensions["B"].width = 32

    if not factors:
        worksheet.cell(row=1, column=1, value=_NO_VALUE)
        return

    fixed, variable = _split_fixed_variable(factors)
    ordered = [*fixed, *variable]
    for column in range(3, 3 + len(ordered)):
        worksheet.column_dimensions[get_column_letter(column)].width = 14

    last_row = _write_factor_table(worksheet, factors, ordered)
    _write_pattern_matrix(worksheet, factors, fixed, variable, last_row + 2)


def _split_fixed_variable(factors: dict[str, dict[int, str]]) -> tuple[list[str], list[str]]:
    """A factor is "Fixed" when every case that set it used the same value."""
    fixed, variable = [], []
    for name, per_case in factors.items():
        target = fixed if len(set(per_case.values())) <= 1 else variable
        target.append(name)
    return fixed, variable


def _write_factor_table(
    worksheet: Worksheet, factors: dict[str, dict[int, str]], ordered: list[str]
) -> int:
    """The "Factor / Element" reference table. Returns the last row written."""
    worksheet.cell(row=1, column=1, value="Factor")
    worksheet.cell(row=1, column=2, value="Element")
    style_table_header_row(worksheet, row=1, start_column=1, columns=2)

    for offset, name in enumerate(ordered, start=1):
        row = 1 + offset
        elements = "/".join(sorted(set(factors[name].values())))
        _write_cell(worksheet, row, 1, name, TOP_LEFT)
        _write_cell(worksheet, row, 2, elements, TOP_WRAP)

    return 1 + len(ordered)


def _write_pattern_matrix(
    worksheet: Worksheet,
    factors: dict[str, dict[int, str]],
    fixed: list[str],
    variable: list[str],
    start_row: int,
) -> None:
    """The per-case matrix: which value each case used for each factor."""
    ordered = [*fixed, *variable]

    worksheet.cell(row=start_row, column=1, value="Test Pattern").font = LABEL_FONT

    group_row = start_row + 1
    header_row = start_row + 2
    _write_group_label(worksheet, group_row, 2, len(fixed), "Fixed Factors")
    _write_group_label(worksheet, group_row, 2 + len(fixed), len(variable), "Variable Factors")
    style_table_header_row(worksheet, row=group_row, start_column=2, columns=len(ordered))

    for column, header in enumerate(["Test Case No.", *ordered], start=1):
        worksheet.cell(row=header_row, column=column, value=header)
    style_table_header_row(worksheet, row=header_row, start_column=1, columns=1 + len(ordered))

    used_case_indices = sorted({index for per_case in factors.values() for index in per_case})
    for offset, case_index in enumerate(used_case_indices, start=1):
        row = header_row + offset
        _write_cell(worksheet, row, 1, str(offset), CENTER)
        for column_offset, name in enumerate(ordered):
            value = factors[name].get(case_index, "-")
            _write_cell(worksheet, row, 2 + column_offset, value, CENTER)


def _write_group_label(
    worksheet: Worksheet, row: int, start_column: int, count: int, label: str
) -> None:
    """One cell of the "Fixed Factors" / "Variable Factors" header, merged over its columns."""
    if count == 0:
        return
    worksheet.cell(row=row, column=start_column, value=label)
    if count > 1:
        worksheet.merge_cells(
            start_row=row, start_column=start_column, end_row=row, end_column=start_column + count - 1
        )


def _write_cell(worksheet: Worksheet, row: int, column: int, value: str, alignment) -> None:
    cell = worksheet.cell(row=row, column=column, value=value)
    cell.alignment = alignment
    cell.border = BORDER
