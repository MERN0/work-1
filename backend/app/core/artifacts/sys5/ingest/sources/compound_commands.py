"""Parser for the compound-commands workbook.

These sheets are not tables: they are a stack of blocks. Each block starts with a row
whose first populated cell reads ``Compound <Name>`` and whose remaining cells carry the
column labels for that block; the rows beneath it are the block's steps, terminated by a
blank row or by the next ``Compound`` row. Column positions drift between blocks, so the
labels are re-read per block rather than assumed.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...models import CompoundCommand, CompoundStep, Provenance
from ...utils.text import clean, normalize
from ..workbook import read_grid

logger = logging.getLogger(__name__)

_COMPOUND_RE = re.compile(r"^\s*compound\s+(?P<name>\S.*?)\s*$", re.IGNORECASE)

#: Header labels, normalised, mapped to the field they populate.
_PARAMETER_LABELS = {"parametersettings", "settings", "parameter"}
_EXPECTED_LABELS = {"expectedvalue", "expected"}
_UNIT_LABELS = {"units", "unit"}
_EXECUTE_LABELS = {"whethertoexecutethecommand", "command", "whethertoexecute", "execute"}
_REMARK_LABELS = {"remarks", "remark"}


class _BlockLayout:
    """Column indices for one block, resolved from its header row."""

    __slots__ = ("keyword", "parameter", "parameter_unit", "expected", "expected_unit",
                 "execute", "remark")

    def __init__(self, keyword_col: int, cells: list[str]) -> None:
        self.keyword = keyword_col
        self.parameter = -1
        self.parameter_unit = -1
        self.expected = -1
        self.expected_unit = -1
        self.execute = -1
        self.remark = -1

        unit_columns: list[int] = []
        for index, cell in enumerate(cells):
            label = normalize(cell)
            if not label:
                continue
            if label in _PARAMETER_LABELS and self.parameter < 0:
                self.parameter = index
            elif label in _EXPECTED_LABELS and self.expected < 0:
                self.expected = index
            elif label in _UNIT_LABELS:
                unit_columns.append(index)
            elif label in _EXECUTE_LABELS and self.execute < 0:
                self.execute = index
            elif label in _REMARK_LABELS and self.remark < 0:
                self.remark = index

        # Two "Units" columns: the one before "Expected Value" qualifies the parameter,
        # the one after qualifies the expected value.
        for column in unit_columns:
            if self.expected >= 0 and column > self.expected:
                if self.expected_unit < 0:
                    self.expected_unit = column
            elif self.parameter_unit < 0:
                self.parameter_unit = column

        # Fall back to the layout the TMHC sheets use when labels are missing.
        if self.parameter < 0:
            self.parameter = keyword_col + 1
        if self.parameter_unit < 0:
            self.parameter_unit = self.parameter + 1

    def read(self, row: list[str], index: int) -> str:
        return clean(row[index]) if 0 <= index < len(row) else ""


def _first_populated(row: list[str]) -> int:
    for index, cell in enumerate(row):
        if clean(cell):
            return index
    return -1


def parse(path: Path, sheet: str, category: str = "set") -> list[CompoundCommand]:
    """Read every ``Compound <Name>`` block from one sheet."""
    grid = read_grid(path, sheet)
    if not grid:
        logger.warning("[sys5] %s[%s]: empty sheet", path.name, sheet)
        return []

    commands: list[CompoundCommand] = []
    current: CompoundCommand | None = None
    layout: _BlockLayout | None = None

    for row_number, row in enumerate(grid, start=1):
        first = _first_populated(row)
        if first < 0:
            # A blank row closes the current block.
            current, layout = None, None
            continue

        match = _COMPOUND_RE.match(row[first])
        if match:
            current = CompoundCommand(
                name=match.group("name"),
                category=category,
                provenance=Provenance(file=path.name, sheet=sheet, row=row_number),
            )
            layout = _BlockLayout(first, row)
            commands.append(current)
            continue

        if current is None or layout is None:
            continue

        keyword = layout.read(row, layout.keyword)
        if not keyword:
            continue

        current.steps.append(
            CompoundStep(
                keyword=keyword,
                parameter=layout.read(row, layout.parameter),
                parameter_unit=layout.read(row, layout.parameter_unit),
                expected=layout.read(row, layout.expected),
                expected_unit=layout.read(row, layout.expected_unit),
                remark=layout.read(row, layout.remark),
            )
        )

    # A block with no steps is a stray label, not a usable command.
    commands = [c for c in commands if c.steps]

    logger.info("[sys5] %s[%s]: %d compound commands (%s)", path.name, sheet, len(commands), category)
    return commands
