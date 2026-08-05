from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, Field

Stage = Literal["pending", "clustered", "generated", "verifying", "verified", "failed"]


class ClusterCheckpoint(BaseModel):
    cluster_id: str
    requirement_ids: list[str] = Field(default_factory=list)
    stage: Stage = "pending"
    correction_attempts: int = 0
    needs_review: bool = False
    last_error: str | None = None
    updated_at: float = Field(default_factory=time.time)


class RunState(BaseModel):
    """The on-disk JSON checkpoint (state/<run_id>.json). This is the primary
    resume mechanism -- it survives process restarts, unlike LangGraph's own
    in-thread checkpointer, which only complements it (ARCHITECTURE.md Sec5)."""

    run_id: str
    domain: str
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    requirement_workbooks: list[str] = Field(default_factory=list)
    supporting_doc_workbooks: list[str] = Field(default_factory=list)
    output_formats: list[str] = Field(default_factory=list)
    clusters: dict[str, ClusterCheckpoint] = Field(default_factory=dict)

    def upsert_cluster(self, checkpoint: ClusterCheckpoint) -> None:
        checkpoint.updated_at = time.time()
        self.clusters[checkpoint.cluster_id] = checkpoint
        self.updated_at = time.time()

    def stage_of(self, cluster_id: str) -> Stage | None:
        entry = self.clusters.get(cluster_id)
        return entry.stage if entry else None

    def is_past_stage(self, cluster_id: str, stage: Stage) -> bool:
        order: list[Stage] = ["pending", "clustered", "generated", "verifying", "verified", "failed"]
        current = self.stage_of(cluster_id)
        if current is None:
            return False
        if current == "failed":
            return False
        return order.index(current) >= order.index(stage)

    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.clusters.values():
            counts[entry.stage] = counts.get(entry.stage, 0) + 1
        counts["needs_review"] = sum(1 for e in self.clusters.values() if e.needs_review)
        return counts
