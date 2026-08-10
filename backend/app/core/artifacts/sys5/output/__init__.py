"""Pluggable output layer.

The pipeline hands this package canonical test cases; a registered
:class:`OutputTemplate` decides what the workbook looks like. Selecting a different
layout is configuration (``output_template`` / ``SYS5_OUTPUT_TEMPLATE``), not a code
change.
"""

from .base import ColumnSpec, OutputTemplate, RenderContext, RenderResult, Row, SheetSpec
from .registry import UnknownTemplateError, available, register, resolve
from .writer import render_workbook

__all__ = [
    "ColumnSpec",
    "OutputTemplate",
    "RenderContext",
    "RenderResult",
    "Row",
    "SheetSpec",
    "UnknownTemplateError",
    "available",
    "register",
    "render_workbook",
    "resolve",
]
