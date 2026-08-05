from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementCluster(BaseModel):
    """A group of requirement IDs the clustering_agent decided belong together.
    Never merges requirements if it would drop coverage of either's testable
    behavior -- when in doubt, the agent keeps clusters small."""

    cluster_id: str
    requirement_ids: list[str]
    rationale: str


class TestPatternFactor(BaseModel):
    """One row of the 'Factors' table on the Test Pattern sheet, e.g.
    Factor=Slope_Angle, Element=Flat/Low/High, Ease_of_Adjustment=Easy."""

    factor: str
    element: str
    ease_of_adjustment: str | None = None


class TestPatternRow(BaseModel):
    """One row of the combinatorial design table: for a given test case number,
    which factors were held fixed and which were varied, and to what values."""

    cluster_id: str
    test_case_no: int
    fixed_values: dict[str, str] = Field(default_factory=dict)
    variable_values: dict[str, str] = Field(default_factory=dict)
