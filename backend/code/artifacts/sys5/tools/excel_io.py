"""Pure-Python xlsx loading helpers. No LLM calls, no cleverness -- read every
sheet, every row, every cell, and hand back plain Python structures. Header
detection / junk-row exclusion is preprocessing's job, not this module's.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl

from logging_setup import get_logger

log = get_logger("excel_io")


def load_workbook_sheets(path: Path) -> dict[str, list[list[Any]]]:
    """Return {sheet_name: [[cell, cell, ...], ...]} for every sheet in the
    workbook, values only (formulas resolved to their last-computed value)."""
    log.info("Loading workbook: %s", path)
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheets: dict[str, list[list[Any]]] = {}
    for name in wb.sheetnames:
        ws = wb[name]
        rows = [list(row) for row in ws.iter_rows(values_only=True)]
        sheets[name] = rows
        log.info("  sheet '%s': %d rows x %d cols", name, len(rows), ws.max_column or 0)
    wb.close()
    return sheets


def header_and_rows(rows: list[list[Any]]) -> tuple[list[str], list[list[Any]]]:
    """Split the first row off as a header. Empty header cells get a
    positional fallback name (COL_1, COL_2, ...) so every column is still
    addressable by key."""
    if not rows:
        return [], []
    raw_header = rows[0]
    header = [
        (str(cell).strip() if cell not in (None, "") else f"COL_{i + 1}")
        for i, cell in enumerate(raw_header)
    ]
    return header, rows[1:]


def row_to_text(row: list[Any]) -> str:
    """Flatten a row into one string for keyword matching / embeddings."""
    return " | ".join(str(c) for c in row if c not in (None, ""))
