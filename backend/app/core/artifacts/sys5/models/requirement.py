"""Requirement-side models: what we read out of the SYS2 workbook."""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

from .knowledge import Provenance

#: DOORS-style identifiers, e.g. ``TMHC_SYSRS_GR005004`` / ``TMHC_SYSRS_IO0009``.
DOORS_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]*_SYSRS_[A-Z]{0,4}\d+\b")

#: Hierarchical section numbers, e.g. ``5.1.1.3``. Requires at least two dots so
#: ordinary decimals ("2.5 km/h") are not mistaken for section references.
SECTION_NO_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")


class FeatureIdentity(BaseModel):
    """The feature a requirement sheet describes.

    Read from the ``Object Heading`` rows at the top of a feature sheet:
    ``Feature Group`` -> "Ramp / Slope Control", ``Feature Name`` -> "005 - Ramp / Slope Control".
    Constant for a whole run; drives the cover title, the ``Feature`` column and the
    workbook metadata.
    """

    model_config = ConfigDict(frozen=True)

    sheet: str
    group: str = ""
    name: str = ""

    @property
    def title(self) -> str:
        """The human title for this feature, with a defined fallback chain.

        Feature Name -> Feature Group -> sheet name. Never empty.
        """
        return self.name or self.group or self.sheet

    @property
    def label(self) -> str:
        """A compact identifier suitable for the ``Feature`` column.

        Strips the leading feature number from a name like ``005 - Ramp / Slope Control``
        and collapses separators, giving ``Ramp_Slope_Control``.
        """
        base = self.name or self.group or self.sheet
        base = re.sub(r"^\s*\d+\s*[-–]\s*", "", base)
        base = re.sub(r"[\s/]+", "_", base.strip())
        return re.sub(r"_+", "_", base).strip("_")


class RequirementRow(BaseModel):
    """One raw row of a requirement sheet, before selection."""

    model_config = ConfigDict(extra="allow")

    requirement_id: str = ""
    object_heading: str = ""
    object_text: str = ""
    category: str = ""
    variant: str = ""
    priority: str = ""
    verification_method: str = ""
    verification_stage: str = ""
    verification_criteria: str = ""
    source: str = ""
    status: str = ""
    remarks: str = ""
    provenance: Provenance
    #: Every non-empty cell of the row, keyed by its header. Keyword selection scans
    #: this so a match in an unmapped column is still found.
    cells: dict[str, str] = Field(default_factory=dict)

    def searchable_text(self) -> str:
        """All cell values joined, for keyword scanning."""
        return " \n".join(v for v in self.cells.values() if v)

    def is_context_row(self) -> bool:
        """True for Heading/Information rows that provide feature context, not requirements."""
        return self.category.strip().lower() in {"heading", "information"}


class Requirement(BaseModel):
    """A selected requirement, enriched with the identifiers traced out of it."""

    model_config = ConfigDict(extra="allow")

    requirement_id: str
    text: str
    heading: str = ""
    category: str = ""
    variant: str = ""
    priority: str = ""
    verification_method: str = ""
    verification_stage: str = ""
    verification_criteria: str = ""
    source: str = ""
    status: str = ""
    remarks: str = ""
    provenance: Provenance
    #: Hierarchical section number found in the row (e.g. "5.1.1.3"), if any.
    section_no: str = ""
    #: DOORS ids referenced by this requirement's text or source column.
    referenced_ids: list[str] = Field(default_factory=list)
    #: Why this row was selected — the keyword that matched, or the fallback rule.
    selected_by: str = ""

    @classmethod
    def from_row(cls, row: RequirementRow, selected_by: str) -> Requirement:
        """Build a selected requirement from a raw sheet row."""
        haystack = f"{row.object_text}\n{row.source}\n{row.requirement_id}\n{row.remarks}"
        sections = SECTION_NO_RE.findall(haystack)
        referenced = [i for i in DOORS_ID_RE.findall(haystack) if i != row.requirement_id]
        return cls(
            requirement_id=row.requirement_id,
            text=row.object_text,
            heading=row.object_heading,
            category=row.category,
            variant=row.variant,
            priority=row.priority,
            verification_method=row.verification_method,
            verification_stage=row.verification_stage,
            verification_criteria=row.verification_criteria,
            source=row.source,
            status=row.status,
            remarks=row.remarks,
            provenance=row.provenance,
            section_no=sections[0] if sections else "",
            referenced_ids=list(dict.fromkeys(referenced)),
            selected_by=selected_by,
        )


class FeatureContext(BaseModel):
    """The Heading/Information rows of a feature sheet (Purpose, Overview, ...).

    Attached to every requirement of that sheet so the planner understands the
    feature as a whole rather than one isolated sentence.
    """

    identity: FeatureIdentity
    #: Ordered ``(heading, text)`` pairs, e.g. ``("Purpose", "Suppress the sliding down ...")``.
    sections: list[tuple[str, str]] = Field(default_factory=list)
    #: Free text found above the header row of the sheet.
    notes: list[str] = Field(default_factory=list)

    def render(self, max_chars: int = 4000) -> str:
        """Render as prompt text, truncated to a character budget."""
        parts = [f"Feature Group: {self.identity.group}", f"Feature Name: {self.identity.name}"]
        for heading, text in self.sections:
            if text:
                parts.append(f"\n{heading}:\n{text}")
        rendered = "\n".join(p for p in parts if p.strip())
        if len(rendered) > max_chars:
            rendered = rendered[:max_chars].rstrip() + "\n[...truncated...]"
        return rendered
