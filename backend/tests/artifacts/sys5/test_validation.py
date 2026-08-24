"""The validators — the guarantee that nothing invented reaches the output."""

from __future__ import annotations

import pytest

from app.core.artifacts.sys5.models import Phase, TestCase, TestCasePlan, TestStep
from app.core.artifacts.sys5.projects import TMHC_PROFILE
from app.core.artifacts.sys5.validation import StepKind, parse_step, validate_case

REMARK = "A remark long enough to satisfy the minimum length rule"


def case_of(*steps: TestStep) -> TestCase:
    case = TestCase(tc_id="TMHC_SQTC_01", description="d", aspect="a", steps=list(steps))
    case.renumber()
    return case


def valid_steps() -> list[TestStep]:
    return [
        TestStep(phase=Phase.PRECONDITION, text="Test_start", remark=REMARK),
        TestStep(phase=Phase.PRECONDITION, text="Set MDL_SWH_VBKY", parameter="ON", remark=REMARK),
        TestStep(
            phase=Phase.ACTION,
            text="Set MDL_SEN_Accelerator_Pedal",
            parameter="30",
            remark=REMARK,
        ),
        TestStep(phase=Phase.ACTION, text="Wait", parameter="2000", parameter_unit="ms", remark=REMARK),
        TestStep(
            phase=Phase.ACTION,
            text="Verify CAN_Main_DispSpeed",
            expected="10 (Config_Tol_Spd)",
            expected_unit="km/h",
            remark=REMARK,
        ),
        TestStep(phase=Phase.POSTCONDITION, text="Compound Key_Off_A1", remark=REMARK),
        TestStep(phase=Phase.POSTCONDITION, text="End_of_test", remark=REMARK),
    ]


def codes_for(steps: list[TestStep], index, plan=None, scoped_names=None) -> list[str]:
    return validate_case(case_of(*steps), index, TMHC_PROFILE, plan, scoped_names).codes()


class TestGrammar:
    @pytest.mark.parametrize(
        ("text", "kind"),
        [
            ("Test_start", StepKind.MARKER),
            ("End_of_test", StepKind.MARKER),
            ("Wait", StepKind.WAIT),
            ("Set MDL_SWH_DIR_STATE", StepKind.SET),
            ("Verify CAN_Main_DispSpeed", StepKind.VERIFY),
            ("Lib_Ramp Accelerator_Sensor(Start=0,Stop=30,Step=1,Time=100)", StepKind.LIBRARY),
            ("Compound Key_Off_A1", StepKind.COMPOUND),
        ],
    )
    def test_legal_forms_parse(self, text: str, kind: StepKind):
        assert parse_step(text, TMHC_PROFILE.allowed_verbs).kind is kind

    @pytest.mark.parametrize(
        "text",
        [
            "Read CAN_Main_DispSpeed",   # declared in the keyword sheet but not permitted
            "Check the speed",
            "Confirm CAN_Main_DispSpeed",
            "Wait 100",                  # duration belongs in the parameter column
            "Set",                       # no target
            "",
        ],
    )
    def test_illegal_forms_are_rejected(self, text: str):
        assert parse_step(text, TMHC_PROFILE.allowed_verbs).kind is StepKind.INVALID

    def test_library_arguments_are_decomposed(self):
        node = parse_step(
            "Lib_Ramp Accelerator_Sensor(Start=0,Stop=30,Step=1,Time=100)",
            TMHC_PROFILE.allowed_verbs,
        )
        assert node.verb == "Lib_Ramp"
        assert node.target == "Accelerator_Sensor"
        assert node.arguments == {"Start": "0", "Stop": "30", "Step": "1", "Time": "100"}


class TestValidCase:
    def test_a_well_formed_case_passes(self, index):
        assert validate_case(case_of(*valid_steps()), index, TMHC_PROFILE).ok


class TestVocabularyEnforcement:
    def test_invented_signal_is_rejected(self, index):
        steps = valid_steps()
        steps[1] = TestStep(
            phase=Phase.PRECONDITION, text="Set Nonexistent_Signal", parameter="ON", remark=REMARK
        )
        assert "UNKNOWN_NAME" in codes_for(steps, index)

    def test_invented_compound_is_rejected(self, index):
        steps = valid_steps()
        steps[5] = TestStep(
            phase=Phase.POSTCONDITION, text="Compound Made_Up_Block", remark=REMARK
        )
        assert "UNKNOWN_COMPOUND" in codes_for(steps, index)

    def test_invented_library_is_rejected(self, index):
        steps = valid_steps()
        steps[3] = TestStep(
            phase=Phase.ACTION, text="Lib_Invented Accelerator_Sensor(A=1)", remark=REMARK
        )
        assert "UNKNOWN_LIBRARY" in codes_for(steps, index)

    def test_wrong_library_arguments_are_rejected(self, index):
        steps = valid_steps()
        steps[3] = TestStep(
            phase=Phase.ACTION,
            text="Lib_Ramp Accelerator_Sensor(Start=0,Finish=30)",
            remark=REMARK,
        )
        assert "BAD_LIBRARY_ARGS" in codes_for(steps, index)

    def test_disallowed_keyword_is_rejected(self, index):
        steps = valid_steps()
        steps[2] = TestStep(phase=Phase.ACTION, text="Read CAN_Main_DispSpeed", remark=REMARK)
        assert "BAD_GRAMMAR" in codes_for(steps, index)

    def test_suggestion_names_a_real_signal(self, index):
        steps = valid_steps()
        steps[1] = TestStep(
            phase=Phase.PRECONDITION, text="Set Accelerater_Sensor", parameter="30", remark=REMARK
        )
        result = validate_case(case_of(*steps), index, TMHC_PROFILE)
        issue = next(i for i in result.issues if i.code == "UNKNOWN_NAME")
        assert "Accelerator_Sensor" in issue.suggestion


class TestScopedVocabulary:
    """A step may reference a name that is real but was never traced to this
    requirement — e.g. a signal that belongs to a different feature or a different
    requirement on the same sheet. Global legality must not be enough to pass."""

    #: Every name the valid steps use, except the CAN signal under test.
    SCOPE_WITHOUT_CAN_SIGNAL = {"MDL_SWH_VBKY", "MDL_SEN_Accelerator_Pedal", "Config_Tol_Spd"}

    def test_globally_legal_but_out_of_scope_name_is_rejected(self, index):
        codes = codes_for(
            valid_steps(), index, scoped_names=self.SCOPE_WITHOUT_CAN_SIGNAL
        )
        assert "OUT_OF_SCOPE_NAME" in codes

    def test_in_scope_name_still_passes(self, index):
        scope = self.SCOPE_WITHOUT_CAN_SIGNAL | {"CAN_Main_DispSpeed"}
        codes = codes_for(valid_steps(), index, scoped_names=scope)
        assert "OUT_OF_SCOPE_NAME" not in codes

    def test_no_scope_given_falls_back_to_global_legality_only(self, index):
        # Backward compatible: omitting scoped_names checks only that the name is real
        # anywhere in the project, as before this check existed.
        assert "OUT_OF_SCOPE_NAME" not in codes_for(valid_steps(), index)

    def test_suggestion_is_drawn_from_the_scope_not_the_whole_project(self, index):
        result = validate_case(
            case_of(*valid_steps()), index, TMHC_PROFILE, scoped_names=self.SCOPE_WITHOUT_CAN_SIGNAL
        )
        issue = next(i for i in result.issues if i.code == "OUT_OF_SCOPE_NAME")
        # The signal actually referenced (CAN_Main_DispSpeed) must never appear in its
        # own suggestion, and only in-scope names may be suggested.
        assert "CAN_Main_DispSpeed" not in issue.suggestion

    def test_suggestion_shows_a_real_readable_name_not_a_normalized_key(self):
        from app.core.artifacts.sys5.validation.vocabulary import _suggest_within

        # scope maps normalized keys -> real display spelling, as check_vocabulary builds
        # it; the target is a near-miss of one entry, so the substring branch fires.
        scope = {"mdlsenacceleratorpedal": "MDL_SEN_Accelerator_Pedal"}
        suggestions = _suggest_within("MDL_SEN_Accelerator_Pedals", scope)
        assert suggestions == ["MDL_SEN_Accelerator_Pedal"]


class TestStructure:
    def test_missing_start_marker(self, index):
        assert "MISSING_START_MARKER" in codes_for(valid_steps()[1:], index)

    def test_missing_end_marker(self, index):
        assert "MISSING_END_MARKER" in codes_for(valid_steps()[:-1], index)

    def test_missing_phase(self, index):
        steps = [s for s in valid_steps() if s.phase is not Phase.POSTCONDITION]
        assert "MISSING_PHASE" in codes_for(steps, index)

    def test_non_contiguous_numbering(self, index):
        case = case_of(*valid_steps())
        case.steps[3].step_no = 99
        assert "BAD_NUMBERING" in validate_case(case, index, TMHC_PROFILE).codes()

    def test_phases_out_of_order(self, index):
        case = case_of(*valid_steps())
        case.steps[1].phase = Phase.POSTCONDITION
        # renumber() sorts by phase, so reorder after numbering to force the violation.
        case.steps[1], case.steps[2] = case.steps[2], case.steps[1]
        for number, step in enumerate(case.steps, start=1):
            step.step_no = number
        assert "PHASE_OUT_OF_ORDER" in validate_case(case, index, TMHC_PROFILE).codes()

    def test_thin_remark(self, index):
        steps = valid_steps()
        steps[2].remark = "set it"
        assert "MISSING_REMARK" in codes_for(steps, index)

    def test_remark_that_only_repeats_the_step(self, index):
        steps = valid_steps()
        steps[2].remark = "Set MDL_SEN_Accelerator_Pedal"
        assert "TRIVIAL_REMARK" in codes_for(steps, index)

    def test_execute_flag_must_be_yes(self, index):
        steps = valid_steps()
        steps[2].execute = "No"
        assert "BAD_EXECUTE_FLAG" in codes_for(steps, index)


class TestSemantics:
    def test_value_outside_the_models_accepted_inputs(self, index):
        steps = valid_steps()
        steps[1] = TestStep(
            phase=Phase.PRECONDITION,
            text="Set MDL_SWH_DIR_STATE",
            parameter="SIDEWAYS",
            remark=REMARK,
        )
        assert "VALUE_NOT_ALLOWED" in codes_for(steps, index)

    def test_accepted_input_passes(self, index):
        steps = valid_steps()
        steps[1] = TestStep(
            phase=Phase.PRECONDITION, text="Set MDL_SWH_DIR_STATE", parameter="FWD", remark=REMARK
        )
        assert "VALUE_NOT_ALLOWED" not in codes_for(steps, index)

    def test_value_outside_a_parameters_declared_range(self, index):
        steps = valid_steps()
        steps[2] = TestStep(
            phase=Phase.ACTION,
            text="Set Maximum_Speed_Limit_Range",
            parameter="99",
            remark=REMARK,
        )
        assert "VALUE_OUT_OF_RANGE" in codes_for(steps, index)

    def test_value_inside_the_range_passes(self, index):
        steps = valid_steps()
        steps[2] = TestStep(
            phase=Phase.ACTION,
            text="Set Maximum_Speed_Limit_Range",
            parameter="10",
            remark=REMARK,
        )
        assert "VALUE_OUT_OF_RANGE" not in codes_for(steps, index)

    @pytest.mark.parametrize("duration", ["", "soon", "-100", "1.5"])
    def test_bad_wait_durations(self, index, duration: str):
        steps = valid_steps()
        steps[3] = TestStep(
            phase=Phase.ACTION, text="Wait", parameter=duration, parameter_unit="ms", remark=REMARK
        )
        codes = codes_for(steps, index)
        assert {"WAIT_WITHOUT_DURATION", "BAD_WAIT_DURATION"} & set(codes)

    def test_wait_unit_must_be_milliseconds(self, index):
        steps = valid_steps()
        steps[3] = TestStep(
            phase=Phase.ACTION, text="Wait", parameter="2", parameter_unit="s", remark=REMARK
        )
        assert "BAD_WAIT_UNIT" in codes_for(steps, index)

    def test_verify_without_an_expected_value(self, index):
        steps = valid_steps()
        steps[4] = TestStep(
            phase=Phase.ACTION, text="Verify CAN_Main_DispSpeed", remark=REMARK
        )
        assert "VERIFY_WITHOUT_EXPECTED" in codes_for(steps, index)

    def test_invented_tolerance_is_rejected(self, index):
        steps = valid_steps()
        steps[4].expected = "10 (Config_Tol_Invented)"
        assert "UNKNOWN_TOLERANCE" in codes_for(steps, index)

    def test_real_tolerance_passes(self, index):
        assert "UNKNOWN_TOLERANCE" not in codes_for(valid_steps(), index)


class TestCoverage:
    def test_planned_values_absent_from_the_steps_are_flagged(self, index):
        plan = TestCasePlan(aspect="a", description="d", ranges_or_boundaries=["42 km/h"])
        assert "COVERAGE_GAP" in codes_for(valid_steps(), index, plan)

    def test_planned_values_present_pass(self, index):
        plan = TestCasePlan(
            aspect="a", description="d", ranges_or_boundaries=["10 (Config_Tol_Spd)"]
        )
        assert "COVERAGE_GAP" not in codes_for(valid_steps(), index, plan)
