"""Robust reading of real-world Excel sheets.

The input workbooks are hand-maintained: header rows sit at arbitrary depths, titles and
notes float above the table, cells are merged both ways, and some sheets are not tables
at all. Everything here exists to turn that into a predictable ``SheetTable`` without
ever guessing at data.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from ..utils.text import clean, normalize

logger = logging.getLogger(__name__)

#: How many rows from the top to consider as header candidates.
DEFAULT_SCAN_ROWS = 15

#: A header candidate must match at least this many expected tokens to win.
MIN_HEADER_SCORE = 2


@dataclass(slots=True)
class TableRow:
    """One data row, addressable by header name."""

    number: int
    values: dict[str, str]

    def get(self, *names: str, default: str = "") -> str:
        """First non-empty value among ``names`` (case/punctuation-insensitive)."""
        for name in names:
            key = normalize(name)
            for header, value in self.values.items():
                if normalize(header) == key and value:
                    return value
        return default

    def non_empty(self) -> dict[str, str]:
        return {k: v for k, v in self.values.items() if v}

    def joined(self) -> str:
        """All values joined — used for keyword scanning across every column."""
        return " \n".join(v for v in self.values.values() if v)


@dataclass(slots=True)
class SheetTable:
    """A parsed sheet: a header row, its data rows, and the free text above it."""

    file: str
    sheet: str
    header_row: int = 0
    headers: list[str] = field(default_factory=list)
    rows: list[TableRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    grid: list[list[str]] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.headers and self.rows)

    def header_index(self, *names: str) -> int:
        """Position of the first matching header, or ``-1``."""
        wanted = [normalize(n) for n in names]
        for index, header in enumerate(self.headers):
            if normalize(header) in wanted:
                return index
        return -1

    def has_headers(self, *names: str) -> bool:
        return self.header_index(*names) >= 0

    def column(self, *names: str) -> list[str]:
        """All values of the first matching column."""
        index = self.header_index(*names)
        if index < 0:
            return []
        key = self.headers[index]
        return [row.values.get(key, "") for row in self.rows]


def _uniquify(headers: list[str]) -> list[str]:
    """Make header names unique while preserving order and original spelling.

    Duplicate headers are real (the output layout has two ``Units`` columns, and the
    feature-number columns repeat across sheets), so later columns get a ``#n`` suffix
    rather than silently overwriting earlier ones.
    """
    seen: dict[str, int] = {}
    result: list[str] = []
    for index, header in enumerate(headers):
        name = header or f"col_{get_column_letter(index + 1)}"
        count = seen.get(name, 0) + 1
        seen[name] = count
        result.append(name if count == 1 else f"{name}#{count}")
    return result


def _expand_merged(worksheet) -> dict[tuple[int, int], str]:
    """Map every cell of a merged range to the range's top-left value.

    Requirement sheets merge vertically (one requirement spanning several rows) and
    horizontally (banner rows); without this, all but the first cell read as empty.
    """
    filled: dict[tuple[int, int], str] = {}
    for merged in worksheet.merged_cells.ranges:
        anchor = clean(worksheet.cell(merged.min_row, merged.min_col).value)
        if not anchor:
            continue
        for row in range(merged.min_row, merged.max_row + 1):
            for col in range(merged.min_col, merged.max_col + 1):
                filled[(row, col)] = anchor
    return filled


@lru_cache(maxsize=128)
def read_grid(path: Path, sheet: str) -> list[list[str]]:
    """Read a whole sheet as a rectangular grid of cleaned strings.

    Merged cells are expanded so every covered cell carries the anchor value.

    Cached because classification probes a sheet before parsing it, and several
    parsers read the same master sheet; a workbook is never read twice.
    """
    workbook = load_workbook(path, data_only=True, read_only=False)
    try:
        if sheet not in workbook.sheetnames:
            return []
        worksheet = workbook[sheet]
        merged = _expand_merged(worksheet)
        grid: list[list[str]] = []
        for r_index, row in enumerate(worksheet.iter_rows(values_only=False), start=1):
            values: list[str] = []
            for c_index, cell in enumerate(row, start=1):
                value = merged.get((r_index, c_index))
                if value is None:
                    value = clean(cell.value)
                values.append(value)
            grid.append(values)
        return grid
    finally:
        workbook.close()


@lru_cache(maxsize=32)
def sheet_names(path: Path) -> tuple[str, ...]:
    """Sheet names of a workbook, cached (each run reads a workbook many times)."""
    workbook = load_workbook(path, data_only=True, read_only=True)
    try:
        return tuple(workbook.sheetnames)
    finally:
        workbook.close()


def _score_header_row(cells: list[str], tokens: set[str]) -> int:
    """How many expected tokens this row's cells match."""
    if not tokens:
        # With no hint, prefer the first densely-populated row.
        return sum(1 for c in cells if c)
    normalized = {normalize(c) for c in cells if c}
    normalized.discard("")
    return sum(1 for token in tokens if token in normalized)


def find_header_row(
    grid: list[list[str]], expected: list[str], scan_rows: int = DEFAULT_SCAN_ROWS
) -> int:
    """Index (0-based, into ``grid``) of the most likely header row.

    Scores each of the first ``scan_rows`` rows by how many ``expected`` header names it
    contains and takes the best. Falls back to the first row with at least two non-empty
    cells, which is what the sheets without a proper table need.
    """
    tokens = {normalize(e) for e in expected if e}
    tokens.discard("")

    best_index, best_score = -1, 0
    limit = min(len(grid), scan_rows)
    for index in range(limit):
        score = _score_header_row(grid[index], tokens)
        if score > best_score:
            best_index, best_score = index, score

    if tokens and best_score >= MIN_HEADER_SCORE:
        return best_index
    if not tokens and best_index >= 0:
        return best_index

    for index in range(limit):
        if sum(1 for c in grid[index] if c) >= 2:
            return index
    return -1


def load_sheet(
    path: Path,
    sheet: str,
    expected_headers: list[str] | None = None,
    scan_rows: int = DEFAULT_SCAN_ROWS,
) -> SheetTable:
    """Parse one sheet into a :class:`SheetTable`.

    ``expected_headers`` are hints, not requirements: they steer header detection but a
    sheet missing some of them still parses. Rows above the header become ``notes`` —
    that is where the Purpose/Overview free text of a requirement sheet lives.
    """
    grid = read_grid(path, sheet)
    table = SheetTable(file=path.name, sheet=sheet, grid=grid)
    if not grid:
        return table

    header_index = find_header_row(grid, expected_headers or [], scan_rows)
    if header_index < 0:
        table.notes = [" | ".join(c for c in row if c) for row in grid[:scan_rows] if any(row)]
        return table

    raw_headers = grid[header_index]
    # Trim trailing empty header cells so we do not invent columns.
    while raw_headers and not raw_headers[-1]:
        raw_headers = raw_headers[:-1]

    table.header_row = header_index + 1
    table.headers = _uniquify([clean(h) for h in raw_headers])
    table.notes = [
        " | ".join(c for c in row if c) for row in grid[:header_index] if any(c for c in row)
    ]

    width = len(table.headers)
    for offset, row in enumerate(grid[header_index + 1 :], start=header_index + 2):
        values = {
            table.headers[i]: (row[i] if i < len(row) else "") for i in range(width)
        }
        if any(values.values()):
            table.rows.append(TableRow(number=offset, values=values))

    logger.debug(
        "[sys5] %s[%s]: header at row %d, %d columns, %d rows",
        path.name,
        sheet,
        table.header_row,
        len(table.headers),
        len(table.rows),
    )
    return table
