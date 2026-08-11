"""``tmhc_v1`` — the TMHC System Qualification Test Case layout."""

from __future__ import annotations

from collections.abc import Iterable

from openpyxl.worksheet.worksheet import Worksheet

from ....models import TestCase
from ...base import ColumnSpec, OutputTemplate, RenderContext, Row, SheetSpec
from ...registry import register
from ...styles import write_stub
from .sheets import configurable_parameters, cover, item_list, test_pattern


class TmhcV1Template(OutputTemplate):
    """The layout shown in the reference ``sys5_test_cases`` workbook."""

    name = "tmhc_v1"
    description = "TMHC SYS5 test cases: Cover, Test Pattern, Item_List, <feature>, Configurable_Parameters"

    # ---------------------------------------------------------------- columns
    def columns(self) -> list[ColumnSpec]:
        """The 16 test-case columns.

        ``Units`` appears twice — once for the parameter and once for the expected
        value. They are addressed by distinct keys and written positionally, so the
        duplicate header is preserved exactly as the customer's sheet has it.
        """
        return [
            ColumnSpec("tc_id", "TestCase ID", 18, merge_per_case=True),
            ColumnSpec("feature", "Feature", 22, wrap=True, merge_per_case=True),
            ColumnSpec("variant", "Variant", 9, merge_per_case=True),
            ColumnSpec("requirement_ids", "Requirement IDs", 16, merge_per_case=True),
            ColumnSpec("priority", "Priority", 9, merge_per_case=True),
            ColumnSpec("mode", "Mode of Execution", 14, merge_per_case=True),
            ColumnSpec("description", "Test Case Description", 44, wrap=True, merge_per_case=True),
            ColumnSpec("phase", "Test Phase", 14, merge_per_phase=True),
            ColumnSpec("step_no", "Step", 6),
            ColumnSpec("text", "Test steps", 38, wrap=True),
            ColumnSpec("parameter", "Parameter Settings", 16, wrap=True),
            ColumnSpec("parameter_unit", "Units", 8),
            ColumnSpec("expected", "Expected Value", 20, wrap=True),
            ColumnSpec("expected_unit", "Units", 8),
            ColumnSpec("execute", "Whether to execute the command", 14, wrap=True),
            ColumnSpec("remark", "Remarks", 60, wrap=True),
        ]

    # ----------------------------------------------------------------- sheets
    def sheets(self) -> list[SheetSpec]:
        return [
            SheetSpec("cover", "Cover"),
            SheetSpec("test_pattern", "Test Pattern"),
            SheetSpec("item_list", "Item_List"),
            SheetSpec("test_cases"),
            SheetSpec("configurable_parameters", "Configurable_Parameters"),
        ]

    def sheet_name(self, spec: SheetSpec, context: RenderContext) -> str:
        """The test-case tab is named after the requirement sheet (``005``)."""
        if spec.key == "test_cases":
            return context.profile.tab_name(context.sheet)
        return spec.name or spec.key

    def write_sheet(
        self, spec: SheetSpec, worksheet: Worksheet, context: RenderContext, cases: list[TestCase]
    ) -> bool:
        if spec.key == "cover":
            cover.write(worksheet, context)
            return True
        if spec.key == "test_pattern":
            test_pattern.write(worksheet, context, cases)
            return True
        if spec.key == "item_list":
            item_list.write(worksheet, context, cases)
            return True
        if spec.key == "configurable_parameters":
            configurable_parameters.write(worksheet, context, cases)
            return True
        if spec.stub:
            write_stub(
                worksheet,
                spec.name or spec.key,
                spec.stub_note.format(sheet=context.profile.tab_name(context.sheet)),
            )
            return True
        return False

    # ------------------------------------------------------------------- rows
    def emit_rows(self, cases: list[TestCase], context: RenderContext) -> Iterable[Row]:
        """One row per step, with a single blank row between test cases."""
        execute_value = context.profile.execute_value

        for case_index, case in enumerate(cases):
            for step in case.steps:
                yield Row(
                    case_index=case_index,
                    phase=step.phase.value,
                    values={
                        "tc_id": case.tc_id,
                        "feature": case.feature,
                        "variant": case.variant,
                        "requirement_ids": case.requirement_ids,
                        "priority": case.priority,
                        "mode": case.mode_of_execution,
                        "description": case.description,
                        "phase": step.phase.value,
                        "step_no": str(step.step_no),
                        "text": step.text,
                        "parameter": step.parameter,
                        "parameter_unit": step.parameter_unit,
                        "expected": step.expected,
                        "expected_unit": step.expected_unit,
                        "execute": step.execute or execute_value,
                        "remark": step.remark,
                    },
                )

            if case_index < len(cases) - 1:
                yield Row(blank=True)


TMHC_V1 = register(TmhcV1Template())

__all__ = ["TMHC_V1", "TmhcV1Template"]
