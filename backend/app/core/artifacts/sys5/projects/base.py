"""Project profiles: everything that varies between customers, in one place.

Adding a project means adding a profile, not editing the pipeline. A profile owns the
rules that are genuinely project-specific — which step verbs are legal, how a test-case
id is formed, whether the requirement column carries a DOORS id or a section number,
which output template to use by default — while the graph, ingestion and validation
stay generic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RequirementIdPolicy(StrEnum):
    """Which identifier form goes in the ``Requirement IDs`` output column."""

    #: Hierarchical section number (``5.1.1.3``); the DOORS id moves to Remarks.
    SECTION = "section"
    #: DOORS-style id (``TMHC_SYSRS_GR005004``); the section number moves to Remarks.
    DOORS = "doors"
    #: Both, joined.
    BOTH = "both"


@dataclass(frozen=True, slots=True)
class ProjectProfile:
    """The per-project rule set."""

    name: str = "generic"

    # --- step grammar -------------------------------------------------------
    #: Primitive verbs. ``Lib_*`` and ``Compound`` are handled by their own productions.
    allowed_verbs: tuple[str, ...] = ("Set", "Wait", "Verify")
    allow_library_calls: bool = True
    allow_compound_calls: bool = True

    # --- structural rules ---------------------------------------------------
    #: First and last step markers. Empty disables the requirement.
    start_marker: str = "Test_start"
    end_marker: str = "End_of_test"
    require_all_phases: bool = True
    #: Every row must carry a remark of at least this many characters.
    min_remark_chars: int = 15
    #: Value written into the "Whether to execute the command" column.
    execute_value: str = "Yes"

    # --- identity -----------------------------------------------------------
    #: ``str.format`` template receiving ``index`` (1-based) and ``feature``.
    tc_id_format: str = "TC_{index:02d}"
    default_priority: str = "P1"
    default_mode_of_execution: str = "Automated"
    requirement_id_policy: RequirementIdPolicy = RequirementIdPolicy.SECTION

    # --- selection ----------------------------------------------------------
    req_keywords: tuple[str, ...] = (
        "sys5 test",
        "sys test",
        "system qualification",
        "system test",
        "sqt",
    )
    #: Category values treated as requirements when the keyword scan finds nothing.
    fallback_categories: tuple[str, ...] = ("functional requirement",)

    # --- output -------------------------------------------------------------
    default_output_template: str = "tmhc_v1"
    #: When true the test-case tab is named after the requirement sheet (``005``).
    name_tab_after_sheet: bool = True
    #: Used when ``name_tab_after_sheet`` is false.
    test_case_tab_name: str = "Test_Cases"

    #: Extra validator codes to downgrade from error to warning for this project.
    tolerated_issue_codes: frozenset[str] = field(default_factory=frozenset)

    def test_case_id(self, index: int, feature: str = "") -> str:
        """Format the id for the ``index``-th test case of a run."""
        return self.tc_id_format.format(index=index, feature=feature)

    def tab_name(self, sheet: str) -> str:
        """Name of the sheet the test cases are written to."""
        return sheet if self.name_tab_after_sheet and sheet else self.test_case_tab_name

    def requirement_id_value(self, section_no: str, doors_id: str) -> str:
        """The value for the ``Requirement IDs`` column under this profile's policy."""
        match self.requirement_id_policy:
            case RequirementIdPolicy.SECTION:
                return section_no or doors_id
            case RequirementIdPolicy.DOORS:
                return doors_id or section_no
            case _:
                return " / ".join(p for p in (section_no, doors_id) if p)

    def requirement_id_remark(self, section_no: str, doors_id: str) -> str:
        """The identifier not written to the column, preserved for traceability."""
        match self.requirement_id_policy:
            case RequirementIdPolicy.SECTION:
                return doors_id if section_no and doors_id else ""
            case RequirementIdPolicy.DOORS:
                return section_no if section_no and doors_id else ""
            case _:
                return ""
