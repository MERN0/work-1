"""Copy-me starter for a new output format.

To add the next customer layout:

1. Copy this directory to ``output/templates/<your_name>/``.
2. Set ``name`` and ``description``, then fill in :meth:`columns` and :meth:`sheets`.
3. Adjust :meth:`emit_rows` if the row shape differs (one row per step is the norm; a
   layout that puts a whole test case on one row would join the steps here instead).
4. Add ``".templates.<your_name>"`` to ``registry._BUILTIN_MODULES``.
5. Select it with ``SYS5_OUTPUT_TEMPLATE=<your_name>`` or ``config["output_template"]``.

Nothing outside this directory needs to change. The contract test in
``tests/artifacts/sys5/test_output_templates.py`` picks the new template up
automatically and checks it renders, so the existing layout cannot regress.

This module is intentionally **not** registered — it is a template for templates, not a
usable layout.
"""

from __future__ import annotations

from collections.abc import Iterable

from ....models import TestCase
from ...base import ColumnSpec, OutputTemplate, RenderContext, Row, SheetSpec


class SkeletonTemplate(OutputTemplate):
    """A minimal but complete output template."""

    name = "skeleton"
    description = "Starter layout — copy, rename and fill in"

    def columns(self) -> list[ColumnSpec]:
        """Declare the output columns in order.

        ``key`` addresses the value, ``header`` is what the reader sees; they are
        separate so a layout may repeat a header (two ``Units`` columns, say) without
        the values colliding.
        """
        return [
            ColumnSpec("tc_id", "Test Case ID", 18, merge_per_case=True),
            ColumnSpec("description", "Description", 40, wrap=True, merge_per_case=True),
            ColumnSpec("phase", "Phase", 14, merge_per_phase=True),
            ColumnSpec("step_no", "Step", 6),
            ColumnSpec("text", "Step", 38, wrap=True),
            ColumnSpec("parameter", "Parameter", 16),
            ColumnSpec("expected", "Expected", 20, wrap=True),
            ColumnSpec("remark", "Remarks", 50, wrap=True),
        ]

    def sheets(self) -> list[SheetSpec]:
        """Declare the tabs in order.

        The spec with key ``"test_cases"`` receives the emitted rows; give any other
        sheet a real renderer in :meth:`write_sheet`, or mark it ``stub=True``.
        """
        return [SheetSpec("test_cases", "Test Cases")]

    def emit_rows(self, cases: list[TestCase], context: RenderContext) -> Iterable[Row]:
        for case_index, case in enumerate(cases):
            for step in case.steps:
                yield Row(
                    case_index=case_index,
                    phase=step.phase.value,
                    values={
                        "tc_id": case.tc_id,
                        "description": case.description,
                        "phase": step.phase.value,
                        "step_no": str(step.step_no),
                        "text": step.text,
                        "parameter": step.parameter,
                        "expected": step.expected,
                        "remark": step.remark,
                    },
                )
            if case_index < len(cases) - 1:
                yield Row(blank=True)
