"""Output templates.

The contract test runs over *every* registered template, so the layout that ships next
is checked by the same rules as the one that ships today — which is what stops a second
format from quietly breaking the first.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from openpyxl import load_workbook

from app.core.artifacts.sys5.models import (
    FeatureContext,
    FeatureIdentity,
    Phase,
    RunSummary,
    TestCase,
    TestStep,
)
from app.core.artifacts.sys5.output import (
    RenderContext,
    UnknownTemplateError,
    available,
    render_workbook,
    resolve,
)
from app.core.artifacts.sys5.projects import TMHC_PROFILE

REMARK = "A remark long enough to satisfy the minimum length rule"


@pytest.fixture
def identity() -> FeatureIdentity:
    return FeatureIdentity(
        sheet="005", group="Ramp / Slope Control", name="005 - Ramp / Slope Control"
    )


@pytest.fixture
def context(identity: FeatureIdentity) -> RenderContext:
    return RenderContext(
        profile=TMHC_PROFILE,
        identity=identity,
        feature=FeatureContext(identity=identity),
        sheet="005",
        project_name="tmhc_demo",
        version="V1.0",
        generated_at=datetime(2026, 8, 10, 15, 0, 0),
        summary=RunSummary(test_cases_generated=2, requirements_selected=2),
    )


def make_case(index: int, aspect: str) -> TestCase:
    case = TestCase(
        tc_id=f"TMHC_SQTC_{index:02d}",
        feature="Ramp_Slope_Control",
        variant="A1",
        requirement_ids="5.1.1.3",
        priority="P1",
        mode_of_execution="Automated",
        description=f"Verify {aspect}",
        aspect=aspect,
        steps=[
            TestStep(phase=Phase.PRECONDITION, text="Test_start", remark=REMARK),
            TestStep(
                phase=Phase.PRECONDITION, text="Set MDL_SWH_VBKY", parameter="ON", remark=REMARK
            ),
            TestStep(
                phase=Phase.ACTION,
                text="Verify CAN_Main_DispSpeed",
                expected="10 (Config_Tol_Spd)",
                expected_unit="km/h",
                remark=REMARK,
            ),
            TestStep(phase=Phase.POSTCONDITION, text="End_of_test", remark=REMARK),
        ],
    )
    case.renumber()
    return case


@pytest.fixture
def cases() -> list[TestCase]:
    return [make_case(1, "forward speed limit"), make_case(2, "reverse speed limit")]


class TestRegistry:
    def test_unknown_template_fails_fast_and_lists_alternatives(self):
        with pytest.raises(UnknownTemplateError) as excinfo:
            resolve("no_such_template")
        assert "tmhc_v1" in str(excinfo.value)

    def test_tmhc_v1_is_registered(self):
        assert "tmhc_v1" in available()


@pytest.mark.parametrize("template_name", available())
class TestTemplateContract:
    """Rules every registered template must satisfy."""

    def test_renders_without_error(self, template_name, cases, context, tmp_path: Path):
        template = resolve(template_name)
        result = render_workbook(template, cases, context, tmp_path / template.filename(context))
        assert result.path.exists()
        assert result.cases == 2

    def test_declares_unique_column_keys(self, template_name, cases, context):
        columns = resolve(template_name).columns()
        keys = [c.key for c in columns]
        assert len(keys) == len(set(keys)), "column keys must be unique even if headers repeat"

    def test_emits_every_step_of_every_case(self, template_name, cases, context):
        template = resolve(template_name)
        rows = [r for r in template.emit_rows(cases, context) if not r.blank]
        assert len(rows) == sum(len(c.steps) for c in cases)

    def test_separates_cases_with_a_blank_row(self, template_name, cases, context):
        rows = list(resolve(template_name).emit_rows(cases, context))
        assert sum(1 for r in rows if r.blank) == len(cases) - 1

    def test_renders_an_empty_run(self, template_name, context, tmp_path: Path):
        template = resolve(template_name)
        result = render_workbook(template, [], context, tmp_path / "empty.xlsx")
        assert result.path.exists()


class TestTmhcV1Layout:
    @pytest.fixture
    def workbook(self, cases, context, tmp_path: Path):
        template = resolve("tmhc_v1")
        path = tmp_path / template.filename(context)
        render_workbook(template, cases, context, path)
        return load_workbook(path)

    def test_filename_carries_sheet_and_timestamp(self, context):
        assert resolve("tmhc_v1").filename(context) == "sys5_005_20260810_150000.xlsx"

    def test_sheet_order_and_names(self, workbook):
        assert workbook.sheetnames == [
            "Cover",
            "Test Pattern",
            "Item_List",
            "005",
            "Configurable_Parameters",
        ]

    def test_test_case_tab_is_named_after_the_requirement_sheet(self, workbook):
        assert "005" in workbook.sheetnames

    def test_exact_column_order_including_the_duplicate_units(self, workbook):
        headers = [c.value for c in workbook["005"][1]]
        assert headers == [
            "TestCase ID",
            "Feature",
            "Variant",
            "Requirement IDs",
            "Priority",
            "Mode of Execution",
            "Test Case Description",
            "Test Phase",
            "Step",
            "Test steps",
            "Parameter Settings",
            "Units",
            "Expected Value",
            "Units",
            "Whether to execute the command",
            "Remarks",
        ]

    def test_cover_title_is_the_feature_name_from_the_requirements(self, workbook):
        assert workbook["Cover"]["C3"].value == "005 - Ramp / Slope Control"

    def test_workbook_title_is_the_feature_name(self, workbook):
        assert workbook.properties.title == "005 - Ramp / Slope Control"

    def test_steps_are_numbered_from_one_per_case(self, workbook):
        sheet = workbook["005"]
        numbers = [sheet.cell(row=r, column=9).value for r in range(2, sheet.max_row + 1)]
        assert numbers == ["1", "2", "3", "4", None, "1", "2", "3", "4"]

    def test_blank_row_sits_between_the_two_cases(self, workbook):
        sheet = workbook["005"]
        assert all(sheet.cell(row=6, column=c).value is None for c in range(1, 17))

    def test_metadata_columns_are_merged_down_each_case(self, workbook):
        merges = {str(m) for m in workbook["005"].merged_cells.ranges}
        assert "A2:A5" in merges  # first case's TestCase ID
        assert "A7:A10" in merges  # second case's

    def test_phase_column_is_merged_per_phase_block(self, workbook):
        merges = {str(m) for m in workbook["005"].merged_cells.ranges}
        assert "H2:H3" in merges  # PRECONDITION spans two steps

    def test_execute_column_is_yes_on_every_step(self, workbook):
        sheet = workbook["005"]
        values = [
            sheet.cell(row=r, column=15).value
            for r in range(2, sheet.max_row + 1)
            if sheet.cell(row=r, column=10).value
        ]
        assert set(values) == {"Yes"}

    def test_pending_sheets_say_so_rather_than_looking_broken(self, workbook):
        for name in ("Test Pattern", "Item_List", "Configurable_Parameters"):
            assert "Layout pending" in workbook[name]["A3"].value
