"""Default output formatter. Column set + five-sheet layout reverse-engineered
from the reference workbook (ARCHITECTURE.md Sec4.1). Pure Python, no LLM
calls -- openpyxl only. Writes through tools.verified_write for the
SHA-256/byte-count integrity check on every save.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from openpyxl.worksheet.worksheet import Worksheet

from formats.base import OutputFormatter
from logging_setup import get_logger, stage
from schemas import ConfigurableParameterEntry, ItemListEntry, TestCase, TestPatternFactor, TestPatternRow, TraceabilityEntry
from tools.verified_write import verified_write_workbook

log = get_logger("default_formatter")

HEADER_FONT = Font(bold=True)
TOP_ALIGN = Alignment(vertical="top", wrap_text=True)


def _write_header(ws: Worksheet, row: int, headers: list[str]) -> None:
    for col, text in enumerate(headers, start=1):
        cell = ws.cell(row=row, column=col, value=text)
        cell.font = HEADER_FONT


class DefaultFormatter(OutputFormatter):
    def write(
        self,
        test_cases: list[TestCase],
        traceability: list[TraceabilityEntry],
        item_list_entries: list[ItemListEntry],
        test_pattern_factors: list[TestPatternFactor],
        test_pattern_rows: list[TestPatternRow],
        configurable_parameters: list[ConfigurableParameterEntry],
        path: Path,
        run_meta: dict,
        output_format_config: dict | None = None,
    ) -> None:
        cfg = output_format_config or {}
        include = cfg.get("include_sheets", {})

        with stage(log, "default_formatter.write", test_cases=len(test_cases), path=str(path)):
            wb = Workbook()
            wb.remove(wb.active)  # replace default 'Sheet' with our named sheets, in a defined order

            if include.get("cover", True):
                self._write_cover(wb, cfg.get("cover_sheet", {}), run_meta)
            if include.get("test_pattern", True):
                self._write_test_pattern(wb, cfg.get("test_pattern_sheet", {}), test_pattern_factors, test_pattern_rows)
            if include.get("item_list", True):
                self._write_item_list(wb, cfg.get("item_list_sheet", {}), item_list_entries)
            self._write_test_cases(wb, cfg.get("test_cases_sheet", {}), test_cases)
            if include.get("configurable_parameters", True):
                self._write_configurable_parameters(wb, cfg.get("configurable_parameters_sheet", {}), configurable_parameters)
            if include.get("traceability", True):
                self._write_traceability(wb, cfg.get("traceability_sheet", {}), traceability)

            verified_write_workbook(path, wb)

    def _write_cover(self, wb: Workbook, sheet_cfg: dict, run_meta: dict) -> None:
        ws = wb.create_sheet(sheet_cfg.get("name", "Cover"))
        ws["A3"] = run_meta.get("change_summary", "")
        ws["A3"].font = Font(bold=True)

        fields = [
            ("Document No.", run_meta.get("document_no", "")),
            ("Version", run_meta.get("version", "")),
            ("Created By:", run_meta.get("created_by", "SYS5 AI Pipeline")),
            ("Verified By:", run_meta.get("verified_by", "SYS5 AI Pipeline")),
        ]
        row = 5
        for label, value in fields:
            ws.cell(row=row, column=4, value=label).font = Font(bold=True)
            ws.cell(row=row, column=5, value=value)
            row += 1

        row += 1
        ws.cell(row=row, column=4, value="Revision History").font = Font(bold=True)
        row += 1
        _write_header(ws, row, ["Revision No:", "Change Description", "Date", "Created by", "Approved by", "Description"])
        row += 1
        for rev in run_meta.get("revision_history", []):
            ws.cell(row=row, column=4, value=rev.get("revision_no", ""))
            ws.cell(row=row, column=5, value=rev.get("change_description", ""))
            ws.cell(row=row, column=6, value=rev.get("date", ""))
            ws.cell(row=row, column=7, value=rev.get("created_by", ""))
            ws.cell(row=row, column=8, value=rev.get("approved_by", ""))
            ws.cell(row=row, column=9, value=rev.get("description", ""))
            row += 1
        log.info("  Cover sheet written")

    def _write_test_pattern(self, wb: Workbook, sheet_cfg: dict, factors: list[TestPatternFactor], rows: list[TestPatternRow]) -> None:
        ws = wb.create_sheet(sheet_cfg.get("name", "Test Pattern"))
        ws.cell(row=1, column=2, value="Factors").font = Font(bold=True)
        _write_header(ws, 2, ["Factor", "Element", "Ease of Adjustment"])
        r = 3
        for f in factors:
            ws.cell(row=r, column=2, value=f.factor)
            ws.cell(row=r, column=3, value=f.element)
            ws.cell(row=r, column=4, value=f.ease_of_adjustment or "")
            r += 1

        r += 2
        ws.cell(row=r, column=2, value="Test Pattern").font = Font(bold=True)
        r += 1
        fixed_keys = sorted({k for row in rows for k in row.fixed_values})
        variable_keys = sorted({k for row in rows for k in row.variable_values})
        headers = ["Cluster", "Test Case No"] + fixed_keys + variable_keys
        _write_header(ws, r, headers)
        r += 1
        for row_data in rows:
            ws.cell(row=r, column=1, value=row_data.cluster_id)
            ws.cell(row=r, column=2, value=row_data.test_case_no)
            col = 3
            for k in fixed_keys:
                ws.cell(row=r, column=col, value=row_data.fixed_values.get(k, ""))
                col += 1
            for k in variable_keys:
                ws.cell(row=r, column=col, value=row_data.variable_values.get(k, ""))
                col += 1
            r += 1
        log.info("  Test Pattern sheet written (%d factor(s), %d pattern row(s))", len(factors), len(rows))

    def _write_item_list(self, wb: Workbook, sheet_cfg: dict, entries: list[ItemListEntry]) -> None:
        ws = wb.create_sheet(sheet_cfg.get("name", "Item_List"))
        write_test_type = sheet_cfg.get("write_test_type_column", False)
        headers = []
        keys = []
        for col in sheet_cfg.get("columns", []):
            if col["key"] == "test_type" and not write_test_type:
                continue
            headers.append(col["header"])
            keys.append(col["key"])
        if not headers:
            headers = ["Feature Name", "Test Case ID", "Applicable Variants", "Execution Required", "Remarks"]
            keys = ["feature_name", "test_case_id", "applicable_variants", "execution_required", "remarks"]

        _write_header(ws, 1, headers)
        row = 2
        for e in entries:
            values = {
                "test_type": e.test_type or "",
                "feature_name": e.feature_name,
                "test_case_id": e.test_case_id,
                "applicable_variants": "/".join(e.applicable_variants),
                "execution_required": "Yes" if e.execution_required else "No",
                "remarks": e.remarks or "",
            }
            for col, key in enumerate(keys, start=1):
                ws.cell(row=row, column=col, value=values.get(key, ""))
            row += 1
        log.info("  Item_List sheet written (%d row(s), test_type column %s)", len(entries), "included" if write_test_type else "omitted")

    def _write_test_cases(self, wb: Workbook, sheet_cfg: dict, test_cases: list[TestCase]) -> None:
        name = sheet_cfg.get("name", "Test_Cases")
        columns = sheet_cfg.get("columns") or [
            {"key": "test_case_id", "header": "Test Case ID"}, {"key": "feature", "header": "Feature"},
            {"key": "applicable_variants", "header": "Applicable Variants"}, {"key": "requirement_ids", "header": "Requirement IDs"},
            {"key": "priority", "header": "Priority"}, {"key": "mode_of_execution", "header": "Mode of Execution"},
            {"key": "description", "header": "Test case Description"}, {"key": "test_phase", "header": "Test Phase"},
            {"key": "step_no", "header": "Step"}, {"key": "step_text", "header": "Test steps"},
            {"key": "parameter_settings", "header": "Parameter Settings"}, {"key": "parameter_units", "header": "Units"},
            {"key": "expected_value", "header": "Expected Value"}, {"key": "expected_units", "header": "Units"},
            {"key": "execute_flag", "header": "Whether to execute the step"}, {"key": "remarks", "header": "Remarks"},
        ]
        merge_keys = set(sheet_cfg.get("merge_columns_across_step_span", []))
        blank_rows = sheet_cfg.get("blank_rows_between_test_cases", 1)

        ws = wb.create_sheet(name)
        keys = [c["key"] for c in columns]
        _write_header(ws, 1, [c["header"] for c in columns])

        row = 2
        for tc in test_cases:
            start_row = row
            for step in tc.steps:
                values = {
                    "test_case_id": tc.id,
                    "feature": tc.feature,
                    "applicable_variants": tc.variant or "",
                    "requirement_ids": ", ".join(tc.traceability),
                    "priority": tc.priority or "",
                    "mode_of_execution": tc.mode_of_execution,
                    "description": tc.description,
                    "test_phase": step.phase.upper(),
                    "step_no": step.step_no,
                    "step_text": step.raw_text,
                    "parameter_settings": ", ".join(f"{k}={v}" for k, v in (step.parameters or {}).items()),
                    "parameter_units": step.parameter_units or "",
                    "expected_value": step.expected_value or "",
                    "expected_units": step.expected_units or "",
                    "execute_flag": "Yes" if step.execute else "No",
                    "remarks": step.remarks or "",
                }
                for col, key in enumerate(keys, start=1):
                    if key in merge_keys and row != start_row:
                        continue  # value only lives in the top cell of the merged span
                    ws.cell(row=row, column=col, value=values.get(key, ""))
                row += 1
            end_row = row - 1

            if end_row > start_row:
                for col, key in enumerate(keys, start=1):
                    if key in merge_keys:
                        ws.merge_cells(start_row=start_row, start_column=col, end_row=end_row, end_column=col)
                        ws.cell(row=start_row, column=col).alignment = TOP_ALIGN

            row += blank_rows  # exactly one (configurable) blank row between test cases

        log.info("  Test_Cases sheet written (%d test case(s))", len(test_cases))

    def _write_configurable_parameters(self, wb: Workbook, sheet_cfg: dict, entries: list[ConfigurableParameterEntry]) -> None:
        ws = wb.create_sheet(sheet_cfg.get("name", "Configurable_Parameters"))
        variants = sorted({v for e in entries for v in e.values_by_variant})
        _write_header(ws, 1, ["Parameter Name", "Description"] + variants)
        row = 2
        for e in entries:
            ws.cell(row=row, column=1, value=e.name)
            ws.cell(row=row, column=2, value=e.description)
            for col, variant in enumerate(variants, start=3):
                ws.cell(row=row, column=col, value=e.values_by_variant.get(variant, "-"))
            row += 1
        log.info("  Configurable_Parameters sheet written (%d parameter(s))", len(entries))

    def _write_traceability(self, wb: Workbook, sheet_cfg: dict, entries: list[TraceabilityEntry]) -> None:
        ws = wb.create_sheet(sheet_cfg.get("name", "Traceability"))
        _write_header(ws, 1, ["Test Case ID", "Requirement IDs"])
        row = 2
        for e in entries:
            ws.cell(row=row, column=1, value=e.test_case_id)
            ws.cell(row=row, column=2, value=", ".join(e.requirement_ids))
            row += 1
        log.info("  Traceability sheet written (%d entrie(s))", len(entries))


FORMATTERS = {
    "default": DefaultFormatter(),
}
