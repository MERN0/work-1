"""The TMHC project profile."""

from __future__ import annotations

from .base import ProjectProfile, RequirementIdPolicy

TMHC_PROFILE = ProjectProfile(
    name="tmhc",
    # Set/Wait/Verify are the primitives; Lib_* and Compound are legal only when the
    # exact signature or block exists in the supporting workbooks. Read is deliberately
    # excluded even though the keyword sheet declares it — it produces console output,
    # not a verifiable assertion, so it has no place in a qualification test case.
    allowed_verbs=("Set", "Wait", "Verify"),
    allow_library_calls=True,
    allow_compound_calls=True,
    variants=("A1", "A2", "B", "C1", "C2", "C3", "D1", "D2"),
    start_marker="Test_start",
    end_marker="End_of_test",
    require_all_phases=True,
    min_remark_chars=15,
    execute_value="Yes",
    tc_id_format="TMHC_SQTC_{index:02d}",
    default_priority="P1",
    default_mode_of_execution="Automated",
    requirement_id_policy=RequirementIdPolicy.SECTION,
    default_output_template="tmhc_v1",
    name_tab_after_sheet=True,
    test_case_tab_name="Test_Cases",
)
