"""LLM node: filtered requirements + supporting-doc registry -> which
supporting-doc rows are relevant to which requirement, reasoned like a human
would since there's no key join between the two (ARCHITECTURE.md Sec3.2)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from llm import is_mock
from logging_setup import get_logger, log_data, stage
from schemas import RequirementRow, SupportingDocItem, SupportingDocUsagePlan

log = get_logger("supporting_doc_planner")

SYSTEM_PROMPT = """You are planning which supporting-document rows are relevant to \
each SYS2 qualification requirement. There is no key/ID join between requirements \
and supporting docs -- infer relevance the way a domain engineer reading both \
documents would: shared signal/parameter names, matching feature area, matching \
variant. If nothing in the supporting docs is relevant to a requirement, return an \
empty relevant_items list and say so in the rationale. Never invent supporting-doc \
rows that weren't provided."""


class _UsagePlanBatch(BaseModel):
    plans: list[SupportingDocUsagePlan] = Field(default_factory=list)


def _mock_plan(requirements: list[RequirementRow], registry: list[SupportingDocItem]) -> list[SupportingDocUsagePlan]:
    plans = []
    for req in requirements:
        req_tokens = {t.lower() for t in req.raw_text.replace("|", " ").split() if len(t) > 3}
        relevant = []
        for item in registry:
            item_text = " ".join(str(v) for v in item.row_data.values())
            item_tokens = {t.lower() for t in item_text.replace("|", " ").split() if len(t) > 3}
            if req_tokens & item_tokens:
                relevant.append(item)
        plans.append(
            SupportingDocUsagePlan(
                requirement_id=req.requirement_id,
                relevant_items=relevant,
                rationale=(
                    f"[MOCK] lexical token overlap: {len(relevant)} supporting-doc row(s) matched"
                    if relevant else "[MOCK] no lexical token overlap found with any supporting-doc row"
                ),
            )
        )
    return plans


def run(llm, requirements: list[RequirementRow], registry: list[SupportingDocItem]) -> list[SupportingDocUsagePlan]:
    with stage(log, "supporting_doc_planner", requirements=len(requirements), registry_items=len(registry)):
        if not registry:
            log.info("Supporting-doc registry is empty -- every requirement gets an empty usage plan")
            plans = [
                SupportingDocUsagePlan(requirement_id=r.requirement_id, relevant_items=[], rationale="no supporting docs supplied")
                for r in requirements
            ]
        elif is_mock(llm):
            log.info("MOCK LLM mode -- using lexical-overlap heuristic instead of a real call")
            plans = _mock_plan(requirements, registry)
        else:
            structured = llm.with_structured_output(_UsagePlanBatch)
            prompt = (
                f"{SYSTEM_PROMPT}\n\nRequirements:\n"
                + "\n".join(f"- {r.requirement_id}: {r.raw_text}" for r in requirements)
                + "\n\nSupporting doc registry:\n"
                + "\n".join(f"- [{i.source_file}/{i.sheet} row {i.row_index}] {i.row_data}" for i in registry)
            )
            result = structured.invoke(prompt)
            plans = result.plans

        for plan in plans:
            log.info("  %s: %d relevant item(s) -- %s", plan.requirement_id, len(plan.relevant_items), plan.rationale)
        log_data(log, "supporting_doc_usage_plans", plans)
        return plans
