"""Helpers shared by the master-sheet parsers."""

from __future__ import annotations

import re

from ...utils.text import feature_key, is_marked
from ..workbook import SheetTable, TableRow

#: ``_uniquify`` appends ``#2``, ``#3`` … to duplicate headers; strip it before
#: interpreting a header as a feature number.
_SUFFIX_RE = re.compile(r"#\d+$")


def feature_columns(table: SheetTable) -> dict[str, str]:
    """Map feature key -> header name for the per-feature "○" columns.

    The master sheets carry one column per feature (``001``…``065``); a mark in that
    column is the authoritative statement that the row belongs to the feature. Headers
    that are not feature numbers (``Signal ID``, ``Remarks``) are ignored.
    """
    columns: dict[str, str] = {}
    for header in table.headers:
        key = feature_key(_SUFFIX_RE.sub("", header))
        if key:
            columns.setdefault(key, header)
    return columns


def marked_features(row: TableRow, columns: dict[str, str]) -> set[str]:
    """Feature keys whose column is marked on this row."""
    return {key for key, header in columns.items() if is_marked(row.values.get(header, ""))}
