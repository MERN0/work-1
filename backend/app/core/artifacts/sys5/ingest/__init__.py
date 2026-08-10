"""Excel ingestion: classification and parsing of the input workbooks."""

from .loader import load_knowledge_base
from .registry import ClassifiedSheet, InputInventory, SourceKind, build_inventory, classify_sheet
from .workbook import SheetTable, TableRow, load_sheet, read_grid, sheet_names

__all__ = [
    "ClassifiedSheet",
    "InputInventory",
    "SheetTable",
    "SourceKind",
    "TableRow",
    "build_inventory",
    "classify_sheet",
    "load_knowledge_base",
    "load_sheet",
    "read_grid",
    "sheet_names",
]
