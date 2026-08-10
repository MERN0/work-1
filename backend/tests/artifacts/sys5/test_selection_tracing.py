"""Requirement selection, vocabulary indexing and tracing."""

from __future__ import annotations

import pytest

from app.core.artifacts.sys5.indexing import (
    VocabularyIndex,
    render_context,
    render_vocabulary,
    trace_requirement,
)
from app.core.artifacts.sys5.models import Requirement
from app.core.artifacts.sys5.nodes.selection import select_requirements
from app.core.artifacts.sys5.projects import TMHC_PROFILE
from app.core.artifacts.sys5.projects import resolve as resolve_profile
from app.core.artifacts.sys5.settings import DEFAULT_REQ_KEYWORDS


class TestSelection:
    def test_keyword_can_match_in_any_column(self, parsed_sheet):
        _, _, rows = parsed_sheet
        selected, reason = select_requirements(rows, DEFAULT_REQ_KEYWORDS, TMHC_PROFILE)

        ids = {r.requirement_id for r in selected}
        # 005010 matches "SYS5 Test" in Verification Stage, 005011 "System Qualification".
        assert ids == {"TMHC_SYSRS_GR005010", "TMHC_SYSRS_GR005011"}
        assert reason.startswith("keyword match")

    def test_rows_without_a_keyword_are_excluded(self, parsed_sheet):
        _, _, rows = parsed_sheet
        selected, _ = select_requirements(rows, DEFAULT_REQ_KEYWORDS, TMHC_PROFILE)
        assert "TMHC_SYSRS_GR005012" not in {r.requirement_id for r in selected}

    def test_heading_and_information_rows_are_never_selected(self, parsed_sheet):
        _, _, rows = parsed_sheet
        selected, _ = select_requirements(rows, DEFAULT_REQ_KEYWORDS, TMHC_PROFILE)
        assert all(r.category.lower() == "functional requirement" for r in selected)

    def test_falls_back_to_category_when_no_keyword_matches(self, parsed_sheet, caplog):
        _, _, rows = parsed_sheet
        selected, reason = select_requirements(rows, ["no_such_keyword"], TMHC_PROFILE)

        assert len(selected) == 3  # every functional requirement on the sheet
        assert reason.startswith("fallback")
        assert all(r.selected_by == "fallback:category" for r in selected)

    def test_identifiers_are_extracted_from_the_row(self, requirement: Requirement):
        assert requirement.section_no == "5.1.1.4"
        assert requirement.requirement_id == "TMHC_SYSRS_GR005011"


class TestVocabularyIndex:
    @pytest.mark.parametrize(
        "name",
        [
            "Accelerator_Sensor",          # I/O logical name
            "TMHC_SYSRS_IO0005",           # its signal id
            "Commanded_RPM",               # CAN logical name
            "DrvL_Rx1_CmdSpd",             # the same signal's bus name
            "CAN_Main_DispSpeed",          # command name
            "MDL_SWH_DIR_STATE",           # model-side signal
            "Key_Off_A1",                  # compound command
            "Lib_Ramp",                    # library function
            "Config_Tol_Spd",              # tolerance
            "Maximum_Speed_Limit_Range",   # app parameter
        ],
    )
    def test_every_naming_convention_resolves(self, index: VocabularyIndex, name: str):
        assert name in index

    def test_lookup_ignores_case_and_punctuation(self, index: VocabularyIndex):
        assert "accelerator sensor" in index
        assert "ACCELERATORSENSOR" in index

    def test_invented_names_are_rejected(self, index: VocabularyIndex):
        assert "Accelerator_Pedal_Position_Sensor_2" not in index
        assert "CAN_Main_TotallyMadeUp" not in index

    def test_suggestions_point_at_real_names(self, index: VocabularyIndex):
        assert "Accelerator_Sensor" in index.suggest("Accelerater_Sensor")


class TestTracing:
    @pytest.fixture
    def pack(self, requirement, knowledge):
        return trace_requirement(requirement, knowledge, feature="5", threshold=85)

    def test_feature_column_membership_traces_exactly(self, pack):
        names = {i.record.name for i in pack.io_signals}
        assert "Accelerator_Sensor" in names
        # Marked against feature 006 only.
        assert "Fork_Height_Sensor" not in names

    def test_feature_evidence_is_recorded(self, pack):
        item = next(i for i in pack.io_signals if i.record.name == "Accelerator_Sensor")
        assert "feature-column:5" in item.reasons
        assert item.score == 100

    def test_commands_are_traced_through_their_can_signal(self, pack):
        item = next(i for i in pack.commands if i.record.name == "CAN_Main_DispSpeed")
        assert "via-can-signal" in item.reasons

    def test_linked_requirement_traces_a_parameter(self, pack):
        item = next(
            i for i in pack.app_parameters if i.record.name == "Maximum_Speed_Limit_Range"
        )
        assert "linked-requirement" in item.reasons

    def test_model_signals_are_always_available(self, pack, knowledge):
        # Preconditions need the key switch and park brake even when the requirement
        # sentence never mentions them.
        traced = {i.record.name for i in pack.model_signals}
        assert traced == {s.name for s in knowledge.model_signals}

    def test_context_render_fits_its_budget(self, pack, knowledge):
        from app.core.artifacts.sys5.indexing import estimate_tokens

        text = render_context(pack, knowledge, budget_tokens=400)
        assert estimate_tokens(text) <= 400

    def test_rendered_context_names_are_all_legal(self, pack, knowledge, index):
        for name in render_vocabulary(pack, knowledge):
            assert name in index


class TestProfileResolution:
    def test_project_name_hint_resolves_the_profile(self):
        assert resolve_profile("", "tmhc_demo", "automotive").name == "tmhc"

    def test_explicit_profile_wins(self):
        assert resolve_profile("generic", "tmhc_demo").name == "generic"

    def test_unknown_hints_fall_back_to_generic(self):
        assert resolve_profile("", "acme_project", "aerospace").name == "generic"
