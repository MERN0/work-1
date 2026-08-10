"""Ingestion: classification, header detection, merged cells and block parsing."""

from __future__ import annotations

from app.core.artifacts.sys5.ingest import SourceKind, load_sheet
from app.core.artifacts.sys5.ingest.sources import compound_commands, configuration_file
from app.core.artifacts.sys5.utils.text import feature_key, is_marked


class TestClassification:
    def test_every_known_sheet_is_classified(self, inventory):
        kinds = {s.kind for s in inventory.sheets}
        assert kinds == {
            SourceKind.REQUIREMENTS,
            SourceKind.COMM_MATRIX,
            SourceKind.IO_SIGNALS,
            SourceKind.APP_PARAMETERS,
            SourceKind.COMMAND_LIST,
            SourceKind.COMPOUND_SET,
            SourceKind.COMPOUND_VERIFY,
            SourceKind.KEYWORD_DESCRIPTION,
            SourceKind.LIBRARY_LIST,
            SourceKind.TOLERANCES,
            SourceKind.CONFIGURATIONS,
            SourceKind.MODEL_INPUT_MAPPING,
            SourceKind.GLOBAL_VARIABLES,
        }

    def test_decorative_sheets_are_skipped_not_misread(self, inventory):
        skipped = " ".join(inventory.skipped)
        assert "Cover Page" in skipped
        assert "Help" in skipped

    def test_feature_sheet_number_is_normalised(self, inventory):
        sheet = inventory.requirement_sheets()[0]
        assert sheet.sheet == "005"
        assert sheet.feature == "5"


class TestHeaderDetection:
    def test_header_found_below_floating_title_rows(self, inventory):
        sheet = inventory.requirement_sheets()[0]
        table = load_sheet(sheet.path, sheet.sheet, ["Requirement ID", "Object Text"])
        # Two title rows sit above the header in the fixture, as in the real file.
        assert table.header_row == 3
        assert table.headers[0] == "Requirement ID"
        assert len(table.notes) == 2

    def test_duplicate_headers_are_kept_distinct(self):
        from app.core.artifacts.sys5.ingest.workbook import _uniquify

        assert _uniquify(["Units", "Units"]) == ["Units", "Units#2"]


class TestMergedCells:
    def test_vertical_merge_is_expanded_to_every_covered_row(self, parsed_sheet):
        _, _, rows = parsed_sheet
        merged = [r for r in rows if r.requirement_id.endswith(("005010", "005011"))]
        assert [r.variant for r in merged] == ["A1", "A1"]

    def test_merged_signal_column_groups_its_inputs(self, knowledge):
        direction = next(s for s in knowledge.model_signals if s.name == "MDL_SWH_DIR_STATE")
        assert direction.allowed_inputs == ["FWD", "NEUTRAL", "BWD"]


class TestFeatureColumns:
    def test_circle_marks_assign_signals_to_features(self, knowledge):
        by_name = {s.name: s for s in knowledge.io_signals}
        assert by_name["Accelerator_Sensor"].features == {"5"}
        assert by_name["Vehicle_Speed"].features == {"4", "5"}
        # Belongs to feature 006 only, so it must not leak into a 005 run.
        assert by_name["Fork_Height_Sensor"].features == {"6"}

    def test_mark_detection(self):
        assert is_marked("○") and is_marked("〇") and is_marked("O")
        assert not is_marked("") and not is_marked("-") and not is_marked("note")

    def test_feature_key_normalisation(self):
        assert feature_key("005") == feature_key(5) == feature_key("5.0") == "5"
        assert feature_key("Signal ID") == ""


class TestCompoundCommands:
    def test_blocks_are_parsed_with_their_steps(self, knowledge):
        by_name = {c.name: c for c in knowledge.compounds}
        assert set(by_name) == {
            "Driving_Initial_Settings",
            "Key_Off_A1",
            "Verifying_Power_On_A1",
        }
        block = by_name["Driving_Initial_Settings"]
        assert [s.keyword for s in block.steps] == [
            "Set MDL_SWH_DIR_STATE",
            "Wait",
            "Set MDL_SWH_Park_Brake",
        ]
        assert block.steps[0].parameter == "FWD"
        assert block.steps[1].parameter == "100"
        assert block.steps[1].parameter_unit == "ms"

    def test_verify_blocks_capture_expected_values(self, knowledge):
        block = next(c for c in knowledge.compounds if c.name == "Verifying_Power_On_A1")
        assert block.category == "verify"
        assert block.steps[0].expected == "52"
        assert block.steps[0].expected_unit == "V"

    def test_blank_row_terminates_a_block(self, inventory):
        sheet = next(s for s in inventory.sheets if s.kind == SourceKind.COMPOUND_SET)
        blocks = compound_commands.parse(sheet.path, sheet.sheet)
        # Without blank-row termination the first block would swallow the second.
        assert len(blocks[0].steps) == 3


class TestSupportingSheets:
    def test_library_signature_is_decomposed(self, knowledge):
        ramp = next(f for f in knowledge.libraries if f.name == "Lib_Ramp")
        assert ramp.parameters == ["Start", "Stop", "Step", "Time"]
        assert ramp.takes_signal is True

        diff = next(f for f in knowledge.libraries if f.name == "Lib_Verify_Diff")
        assert diff.parameters == ["Signal_1", "Signal_2", "Condition"]

    def test_tolerance_pair_is_split(self, knowledge):
        speed = next(t for t in knowledge.tolerances if t.name == "Config_Tol_Spd")
        assert (speed.positive, speed.negative) == ("0.5", "1.5")

    def test_configuration_enum_is_parsed(self, knowledge):
        enum = knowledge.configurations[0]
        assert enum.values["0x00"] == "H"
        assert enum.values["0x10"] == "Original Mode"

    def test_app_parameter_ranges_are_read(self, knowledge):
        parameter = next(
            p for p in knowledge.app_parameters if p.name == "Maximum_Speed_Limit_Range"
        )
        assert (parameter.min_value, parameter.max_value) == ("2", "20")
        assert parameter.linked_requirement == "TMHC_SYSRS_GR005011"

    def test_global_variables_parse_with_an_unknown_layout(self, inventory):
        sheet = next(s for s in inventory.sheets if s.kind == SourceKind.GLOBAL_VARIABLES)
        variables = configuration_file.parse_global_variables(sheet.path, sheet.sheet)
        assert variables[0].name == "Global_Test_Mode"
        assert variables[0].value == "HIL"


class TestFeatureIdentity:
    def test_identity_read_from_object_heading_rows(self, parsed_sheet):
        identity, _, _ = parsed_sheet
        assert identity.group == "Ramp / Slope Control"
        assert identity.name == "005 - Ramp / Slope Control"
        assert identity.title == "005 - Ramp / Slope Control"
        assert identity.label == "Ramp_Slope_Control"

    def test_title_falls_back_through_group_to_sheet_name(self):
        from app.core.artifacts.sys5.models import FeatureIdentity

        assert FeatureIdentity(sheet="007", group="Braking").title == "Braking"
        assert FeatureIdentity(sheet="007").title == "007"

    def test_context_sections_are_collected_and_ordered(self, parsed_sheet):
        _, context, _ = parsed_sheet
        assert [heading for heading, _ in context.sections] == ["Purpose", "Overview"]
        assert "regenerative breaking" in context.render()
