from __future__ import annotations

from pydantic import BaseModel, Field


class SupportingDocItem(BaseModel):
    """One row from a supporting document, normalized into the in-memory registry."""

    source_file: str
    sheet: str
    row_index: int
    row_data: dict[str, str] = Field(default_factory=dict)


class SupportingDocUsagePlan(BaseModel):
    """LLM-produced relevance plan: which supporting-doc rows matter for a
    requirement, and why. There is no key join between requirements and
    supporting docs, so this reasoning step is what stands in for one."""

    requirement_id: str
    relevant_items: list[SupportingDocItem] = Field(default_factory=list)
    rationale: str
