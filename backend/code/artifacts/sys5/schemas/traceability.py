from __future__ import annotations

from pydantic import BaseModel, Field


class TraceabilityEntry(BaseModel):
    """Built deterministically from cluster membership + generation metadata --
    never re-guessed by an LLM."""

    test_case_id: str
    requirement_ids: list[str] = Field(default_factory=list)
