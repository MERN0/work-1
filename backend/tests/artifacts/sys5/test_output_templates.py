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


#: Minimal, deliberately partial lookup — Configurable_Parameters must render fine for a
#: name it has no description for, not just the documented ones.
_DESCRIPTIONS = {"MDL_SWH_VBKY": "Key switch input to the drive controller"}


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
        describe=lambda name: _DESCRIPTIONS.get(name, ""),
        available_variants=TMHC_PROFILE.variants,
    )


def make_case(
    index: int, aspect: str, variant: str, test_type: str, pedal_value: str
) -> TestCase:
    case = TestCase(
        tc_id=f"TMHC_SQTC_{index:02d}",
        feature="Ramp_Slope_Control",
        variant=variant,
        requirement_ids="5.1.1.3",
        priority="P1",
        mode_of_execution="Automated",
        description=f"Verify {aspect}",
        aspect=aspect,
        test_type=test_type,
        steps=[
            TestStep(phase=Phase.PRECONDITION, text="Test_start", remark=REMARK),
            TestStep(
                phase=Phase.PRECONDITION, text="Set MDL_SWH_VBKY", parameter="ON", remark=REMARK
            ),
            TestStep(
                phase=Phase.ACTION,
                text="Set MDL_SEN_Accelerator_Pedal",
                parameter=pedal_value,
                remark=REMARK,
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
    return [
        make_case(1, "forward speed limit", variant="A2", test_type="Boundary", pedal_value="30"),
        make_case(2, "reverse speed limit", variant="A1", test_type="Normal_System", pedal_value="0"),
    ]


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
        assert numbers == ["1", "2", "3", "4", "5", None, "1", "2", "3", "4", "5"]

    def test_blank_row_sits_between_the_two_cases(self, workbook):
        sheet = workbook["005"]
        assert all(sheet.cell(row=7, column=c).value is None for c in range(1, 17))

    def test_metadata_columns_are_merged_down_each_case(self, workbook):
        merges = {str(m) for m in workbook["005"].merged_cells.ranges}
        assert "A2:A6" in merges  # first case's TestCase ID
        assert "A8:A12" in merges  # second case's

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

class TestItemList:
    @pytest.fixture
    def sheet(self, cases, context, tmp_path: Path):
        template = resolve("tmhc_v1")
        path = tmp_path / "item_list.xlsx"
        render_workbook(template, cases, context, path)
        return load_workbook(path)["Item_List"]

    def test_headers(self, sheet):
        assert [c.value for c in sheet[1]] == [
            "Sl.No",
            "Test Type",
            "Feature Name",
            "Test Case ID",
            "Applicable Variants",
            "Execution Required",
            "Remarks",
        ]

    def test_one_row_per_case_no_repetition(self, sheet):
        assert sheet.max_row == 3  # header + exactly 2 cases, not padded or duplicated

    def test_row_values_come_straight_from_the_case(self, sheet):
        # openpyxl reads back an empty-string cell as None, not "".
        assert [sheet.cell(row=2, column=c).value for c in range(1, 8)] == [
            "1", "Boundary", "forward speed limit", "TMHC_SQTC_01", "A2", "Yes", None,
        ]
        assert [sheet.cell(row=3, column=c).value for c in range(1, 8)] == [
            "2", "Normal_System", "reverse speed limit", "TMHC_SQTC_02", "A1", "Yes", None,
        ]

    def test_unresolved_case_gets_a_review_remark(self, cases, context, tmp_path: Path):
        from app.core.artifacts.sys5.models import ValidationIssue

        cases[0].issues = [ValidationIssue(code="UNKNOWN_NAME", message="x")]
        path = tmp_path / "item_list_flagged.xlsx"
        render_workbook(resolve("tmhc_v1"), cases, context, path)
        sheet = load_workbook(path)["Item_List"]
        assert sheet.cell(row=2, column=7).value == "Needs review: UNKNOWN_NAME"


class TestConfigurableParameters:
    @pytest.fixture
    def sheet(self, cases, context, tmp_path: Path):
        template = resolve("tmhc_v1")
        path = tmp_path / "config_params.xlsx"
        render_workbook(template, cases, context, path)
        return load_workbook(path)["Configurable_Parameters"]

    def test_headers_show_only_variants_present_in_this_run(self, sheet):
        # cases use A2 and A1; A1 sorts first in the profile's canonical order even
        # though case index 0 uses A2 — the column order follows the profile, not
        # discovery order. B/C1/.../D2 never appear because no case used them.
        assert [c.value for c in sheet[1]] == ["Parameter Name", "Description", "A1", "A2"]

    def test_lists_only_names_actually_used_no_repetition(self, sheet):
        names = [sheet.cell(row=r, column=1).value for r in range(2, sheet.max_row + 1)]
        assert names == [
            "MDL_SWH_VBKY",
            "MDL_SEN_Accelerator_Pedal",
            "CAN_Main_DispSpeed",
            "Config_Tol_Spd",
        ]
        assert len(names) == len(set(names))

    def test_description_comes_from_the_context_lookup(self, sheet):
        assert sheet.cell(row=2, column=1).value == "MDL_SWH_VBKY"
        assert sheet.cell(row=2, column=2).value == "Key switch input to the drive controller"

    def test_undocumented_name_gets_an_empty_description_not_a_crash(self, sheet):
        assert sheet.cell(row=3, column=2).value in (None, "")

    def test_variant_cells_are_dashes_not_invented_values(self, sheet):
        for row in range(2, sheet.max_row + 1):
            assert sheet.cell(row=row, column=3).value == "-"
            assert sheet.cell(row=row, column=4).value == "-"


class TestTestPattern:
    @pytest.fixture
    def sheet(self, cases, context, tmp_path: Path):
        template = resolve("tmhc_v1")
        path = tmp_path / "test_pattern.xlsx"
        render_workbook(template, cases, context, path)
        return load_workbook(path)["Test Pattern"]

    def test_factor_table_lists_only_set_targets_actually_used(self, sheet):
        assert sheet.cell(row=1, column=1).value == "Factor"
        assert sheet.cell(row=2, column=1).value == "MDL_SWH_VBKY"
        assert sheet.cell(row=2, column=2).value == "ON"
        assert sheet.cell(row=3, column=1).value == "MDL_SEN_Accelerator_Pedal"
        assert sheet.cell(row=3, column=2).value == "0/30"

    def test_verify_targets_are_not_treated_as_factors(self, sheet):
        names = {sheet.cell(row=r, column=1).value for r in (2, 3)}
        assert "CAN_Main_DispSpeed" not in names

    def test_fixed_vs_variable_grouping(self, sheet):
        assert sheet.cell(row=6, column=2).value == "Fixed Factors"
        assert sheet.cell(row=6, column=3).value == "Variable Factors"
        assert [c.value for c in sheet[7]][:3] == [
            "Test Case No.",
            "MDL_SWH_VBKY",
            "MDL_SEN_Accelerator_Pedal",
        ]

    def test_matrix_rows_match_what_each_case_actually_set(self, sheet):
        assert [sheet.cell(row=8, column=c).value for c in (1, 2, 3)] == ["1", "ON", "30"]
        assert [sheet.cell(row=9, column=c).value for c in (1, 2, 3)] == ["2", "ON", "0"]

    def test_empty_run_says_so_without_erroring(self, context, tmp_path: Path):
        path = tmp_path / "test_pattern_empty.xlsx"
        render_workbook(resolve("tmhc_v1"), [], context, path)
        sheet = load_workbook(path)["Test Pattern"]
        assert "No test case set" in sheet.cell(row=1, column=1).value
