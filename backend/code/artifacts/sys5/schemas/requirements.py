from __future__ import annotations

from pydantic import BaseModel, Field


class RequirementRow(BaseModel):
    """One filtered SYS2 requirement row. Keeps every original column plus
    provenance, so nothing the LLM nodes might need is dropped in preprocessing."""

    requirement_id: str
    source_file: str
    source_sheet: str
    row_index: int
    columns: dict[str, str] = Field(default_factory=dict, description="original column name -> cell value")
    raw_text: str = Field(description="concatenation of all cell values, used for matching/embedding")
