"""LLM node, strict: requirements + supporting-doc usage plan -> clusters.
Never merges two requirements into one cluster if doing so would drop
coverage of either's testable behavior -- when in doubt, keep separate
(ARCHITECTURE.md Sec3.3, carried from the master prompt)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import is_mock
from logging_setup import get_logger, log_data, stage
from schemas import RequirementCluster, RequirementRow, SupportingDocUsagePlan

log = get_logger("clustering_agent")

SYSTEM_PROMPT = """You cluster SYS2 qualification requirements into groups that will \
each become one HIL test-case-generation unit. STRICT RULE: never merge two \
requirements into one cluster if doing so would drop coverage of either \
requirement's testable behavior. When in doubt, keep them in separate clusters. \
Only merge requirements that are testing genuinely the same behavior/feature from \
angles that belong in one coherent set of test cases."""


class _ClusterBatch(BaseModel):
    clusters: list[RequirementCluster] = Field(default_factory=list)


def _mock_clusters(requirements: list[RequirementRow]) -> list[RequirementCluster]:
    # Safe mock default: one cluster per requirement -- satisfies "when in doubt,
    # keep separate" without needing real semantic judgement.
    return [
        RequirementCluster(
            cluster_id=f"CLUSTER_{i + 1:03d}",
            requirement_ids=[r.requirement_id],
            rationale="[MOCK] one requirement per cluster (no semantic merging performed)",
        )
        for i, r in enumerate(requirements)
    ]


def run(llm, requirements: list[RequirementRow], usage_plans: list[SupportingDocUsagePlan]) -> list[RequirementCluster]:
    with stage(log, "clustering_agent", requirements=len(requirements)):
        if not requirements:
            log.warning("No requirements to cluster")
            return []

        if is_mock(llm):
            log.info("MOCK LLM mode -- one cluster per requirement")
            clusters = _mock_clusters(requirements)
        else:
            structured = llm.with_structured_output(_ClusterBatch)
            plan_by_req = {p.requirement_id: p for p in usage_plans}
            prompt = (
                f"{SYSTEM_PROMPT}\n\nRequirements (with supporting-doc relevance):\n"
                + "\n".join(
                    f"- {r.requirement_id}: {r.raw_text}"
                    f" | relevant supporting items: {len(plan_by_req[r.requirement_id].relevant_items) if r.requirement_id in plan_by_req else 0}"
                    for r in requirements
                )
            )
            result = structured.invoke(prompt)
            clusters = result.clusters

        all_req_ids = {r.requirement_id for r in requirements}
        clustered_ids = {rid for c in clusters for rid in c.requirement_ids}
        missing = all_req_ids - clustered_ids
        if missing:
            log.warning("%d requirement(s) not placed in any cluster by the LLM -- adding singleton clusters: %s", len(missing), missing)
            for rid in missing:
                clusters.append(RequirementCluster(cluster_id=f"CLUSTER_FALLBACK_{rid}", requirement_ids=[rid], rationale="fallback: LLM omitted this requirement"))

        for c in clusters:
            log.info("  %s: %d requirement(s) -- %s", c.cluster_id, len(c.requirement_ids), c.rationale)
        log_data(log, "clusters", clusters)
        return clusters
