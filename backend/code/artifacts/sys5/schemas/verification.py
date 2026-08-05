from __future__ import annotations

from pydantic import BaseModel, Field


class VerificationResult(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    correction_attempt: int = 0
