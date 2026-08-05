"""LangGraph StateGraph assembly (ARCHITECTURE.md Sec3.7).

Current LangGraph API confirmed before writing this (ARCHITECTURE.md Sec7):
StateGraph/START/END from langgraph.graph, add_node/add_edge,
.compile(checkpointer=...), InMemorySaver from langgraph.checkpoint.memory.

One deliberate simplification vs. the Phase 1 architecture sketch: the
generate<->verify retry loop is implemented as a bounded internal loop inside
verification_correction_agent (max 2 attempts, see subagents/
verification_correction_agent.py) rather than as a graph-level conditional
edge back into test_case_generator. The master prompt describes
verification_correction_agent as a single node with its own internal loop --
that's simpler than fanning per-cluster retries out across the graph with
LangGraph's Send API, and behaves identically from the outside (bounded
2-attempt loop, keep-with-needs_review on exhaustion). Flagging this here
since ARCHITECTURE.md Sec3.7 sketched the conditional-edge version.

The per-cluster checkpoint skip/resume loop (ARCHITECTURE.md Sec5) lives
inside generate_and_verify_node's for-loop over clusters, not as separate
graph nodes per cluster, for the same reason.

Compiled WITHOUT langgraph's own checkpointer: InMemorySaver requires every
value in GraphState to be msgpack-serializable, but GraphState intentionally
carries live objects (the LLM client, RunConfig, a Path) because the JSON
checkpoint file (checkpoint_store.py) is the declared primary resume
mechanism, not langgraph's in-thread one (ARCHITECTURE.md Sec5). InMemorySaver
is still imported/demonstrated below for a future cut where GraphState is
trimmed to serializable primitives only.
"""

from __future__ import annotations

import operator
from pathlib import Path
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

import checkpoint_store
from config_loader import RunConfig
from logging_setup import get_logger, stage
from schemas import (
    ConfigurableParameterEntry,
    ItemListEntry,
    RequirementCluster,
    RequirementRow,
    RunState,
    SupportingDocItem,
    SupportingDocUsagePlan,
    TestCase,
    TestPatternFactor,
    TestPatternRow,
    TraceabilityEntry,
)
from subagents import clustering_agent, domain_prompt_injector, supporting_doc_planner, test_case_generator, verification_correction_agent

log = get_logger("graph")


class GraphState(TypedDict):
    config: RunConfig
    llm: Any
    run_state: RunState
    state_dir: Path

    requirements: list[RequirementRow]
    requirements_by_id: dict[str, RequirementRow]
    supporting_docs: list[SupportingDocItem]
    configurable_parameters: list[ConfigurableParameterEntry]

    domain_prompt_text: str
    usage_plans: list[SupportingDocUsagePlan]
    clusters: list[RequirementCluster]

    verified_test_cases: Annotated[list[TestCase], operator.add]
    item_list_entries: Annotated[list[ItemListEntry], operator.add]
    test_pattern_factors: Annotated[list[TestPatternFactor], operator.add]
    test_pattern_rows: Annotated[list[TestPatternRow], operator.add]

    traceability: list[TraceabilityEntry]
    output_paths: dict[str, str]


def domain_prompt_injector_node(state: GraphState) -> dict:
    text = domain_prompt_injector.run(state["config"])
    return {"domain_prompt_text": text}


def supporting_doc_planner_node(state: GraphState) -> dict:
    plans = supporting_doc_planner.run(state["llm"], state["requirements"], state["supporting_docs"])
    return {"usage_plans": plans}


def clustering_agent_node(state: GraphState) -> dict:
    clusters = clustering_agent.run(state["llm"], state["requirements"], state["usage_plans"])

    run_state = state["run_state"]
    for c in clusters:
        if c.cluster_id not in run_state.clusters:
            from schemas import ClusterCheckpoint
            run_state.upsert_cluster(ClusterCheckpoint(cluster_id=c.cluster_id, requirement_ids=c.requirement_ids, stage="clustered"))
    checkpoint_store.save(run_state, state["state_dir"])

    return {"clusters": clusters}


def generate_and_verify_node(state: GraphState) -> dict:
    """Batches together what ARCHITECTURE.md Sec3.7 originally sketched as two
    separate nodes (test_case_generator, verification_correction_agent),
    looping over clusters sequentially so Test Case ID sequencing stays
    deterministic and the JSON checkpoint can be updated cluster-by-cluster."""
    config = state["config"]
    llm = state["llm"]
    run_state = state["run_state"]
    state_dir = state["state_dir"]
    requirements_by_id = state["requirements_by_id"]
    domain_prompt_text = state["domain_prompt_text"]
    usage_plans = state["usage_plans"]

    all_verified: list[TestCase] = []
    all_item_list: list[ItemListEntry] = []
    all_pattern_factors: list[TestPatternFactor] = []
    all_pattern_rows: list[TestPatternRow] = []
    sequence = config.id_format.get("start_at", 1)

    with stage(log, "generate_and_verify_node", clusters=len(state["clusters"])):
        for cluster in state["clusters"]:
            if run_state.is_past_stage(cluster.cluster_id, "verified"):
                log.info("Cluster %s already verified in a prior run -- reloading from disk instead of regenerating", cluster.cluster_id)
                reloaded = checkpoint_store.load_cluster_test_cases(run_state.run_id, cluster.cluster_id, "verified", state_dir)
                if reloaded is not None:
                    all_verified.extend(reloaded)
                    sequence += len(reloaded)
                    continue
                log.warning("Cluster %s marked verified but no cached artifact found -- regenerating", cluster.cluster_id)

            test_cases, item_list_entries, pattern_factors, pattern_rows, sequence = test_case_generator.run(
                llm, config, cluster, requirements_by_id, domain_prompt_text, sequence,
            )
            cp = run_state.clusters[cluster.cluster_id]
            cp.stage = "generated"
            checkpoint_store.save_cluster_test_cases(run_state.run_id, cluster.cluster_id, "generated", test_cases, state_dir)
            checkpoint_store.save(run_state, state_dir)

            verified = verification_correction_agent.run(llm, config, test_cases, usage_plans)
            cp.stage = "verified"
            cp.needs_review = any(tc.needs_review for tc in verified)
            checkpoint_store.save_cluster_test_cases(run_state.run_id, cluster.cluster_id, "verified", verified, state_dir)
            checkpoint_store.save(run_state, state_dir)

            all_verified.extend(verified)
            all_item_list.extend(item_list_entries)
            all_pattern_factors.extend(pattern_factors)
            all_pattern_rows.extend(pattern_rows)

        log.info("generate_and_verify_node complete: %d test case(s) across %d cluster(s)", len(all_verified), len(state["clusters"]))

    return {
        "verified_test_cases": all_verified,
        "item_list_entries": all_item_list,
        "test_pattern_factors": all_pattern_factors,
        "test_pattern_rows": all_pattern_rows,
    }


def build_traceability_node(state: GraphState) -> dict:
    """Pure Python, deterministic -- built from cluster membership +
    generation metadata (test_case.traceability), never re-guessed by an LLM."""
    with stage(log, "build_traceability_node"):
        entries = [TraceabilityEntry(test_case_id=tc.id, requirement_ids=tc.traceability) for tc in state["verified_test_cases"]]
        log.info("Built %d traceability entries", len(entries))
        return {"traceability": entries}


def build_graph():
    graph = StateGraph(GraphState)
    graph.add_node("domain_prompt_injector", domain_prompt_injector_node)
    graph.add_node("supporting_doc_planner", supporting_doc_planner_node)
    graph.add_node("clustering_agent", clustering_agent_node)
    graph.add_node("generate_and_verify", generate_and_verify_node)
    graph.add_node("build_traceability", build_traceability_node)

    graph.add_edge(START, "domain_prompt_injector")
    graph.add_edge("domain_prompt_injector", "supporting_doc_planner")
    graph.add_edge("supporting_doc_planner", "clustering_agent")
    graph.add_edge("clustering_agent", "generate_and_verify")
    graph.add_edge("generate_and_verify", "build_traceability")
    graph.add_edge("build_traceability", END)

    # See module docstring: no checkpointer -- GraphState isn't msgpack-serializable
    # by design, and the JSON file in checkpoint_store.py is the real resume path.
    return graph.compile()
