"""The LangGraph pipeline.

    parse -> select -> plan -> [Send fan-out] -> generate+validate+repair -> render

The fan-out is a ``Send`` from a conditional edge: one branch per planned test case, so
the number of parallel branches is decided at runtime from what the planner produced.
Each branch generates, validates and repairs its own case independently, and the
reducer on ``generated`` collects them.

Heavy objects live on :class:`Sys5Pipeline` and are captured by the node closures rather
than passed through state — checkpoints stay small and the chat model never has to be
serialised.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, Send

from .indexing import (
    VocabularyIndex,
    render_context,
    render_vocabulary,
    trace_requirement,
)
from .ingest import InputInventory, build_inventory, load_knowledge_base
from .ingest.sources import requirements as requirements_source
from .llm import StructuredCaller
from .models import (
    FeatureContext,
    FeatureIdentity,
    KnowledgeBase,
    RunSummary,
    TestCase,
    TestCasePlan,
)
from .nodes.assembly import build_test_case
from .nodes.selection import select_requirements
from .output import OutputTemplate, RenderContext, render_workbook
from .projects import ProjectProfile
from .prompts import (
    GeneratedStep,
    PlanResponse,
    StepsResponse,
    generator_prompt,
    planner_prompt,
    repair_prompt,
    system_prompt,
)
from .settings import Sys5Settings
from .utils.json_store import JsonStore
from .validation import ValidationResult, summarise, validate_case

logger = logging.getLogger(__name__)

#: Retry transport-level failures inside a node before the branch is abandoned.
NODE_RETRY = RetryPolicy(max_attempts=2, initial_interval=1.0, backoff_factor=2.0)


@dataclass(slots=True)
class SheetRun:
    """Everything resolved for one requirement sheet before the graph runs."""

    sheet: str
    feature_key: str
    identity: FeatureIdentity
    feature_context: FeatureContext
    rows: list


class Sys5Pipeline:
    """Owns the run's resources and builds the graph over them."""

    def __init__(
        self,
        settings: Sys5Settings,
        profile: ProjectProfile,
        template: OutputTemplate,
        knowledge: KnowledgeBase,
        index: VocabularyIndex,
        caller: StructuredCaller | None,
        store: JsonStore,
    ) -> None:
        self.settings = settings
        self.profile = profile
        self.template = template
        self.knowledge = knowledge
        self.index = index
        self.caller = caller
        self.store = store
        self.system = system_prompt(profile)

    # ------------------------------------------------------------------ nodes
    def select(self, state) -> dict:
        """Choose the requirements this sheet's run must cover."""
        rows = state["rows"]
        selected, reason = select_requirements(rows, self.settings.req_keywords, self.profile)

        self.store.save(
            f"selected_{state['sheet']}",
            {"reason": reason, "requirements": selected, "scanned": len(rows)},
        )
        logger.info(
            "[sys5] sheet %s: selected %d of %d rows by %s",
            state["sheet"],
            len(selected),
            len(rows),
            reason,
        )
        return {"requirements": selected, "selection_reason": reason}

    def plan(self, state) -> dict:
        """Ask the model, once per requirement, what test cases are needed."""
        from .state import GenerationTask

        tasks: list[GenerationTask] = []
        budget = self.settings.llm.prompt_budget
        feature_context = state["feature_context"]

        for requirement in state["requirements"]:
            pack = trace_requirement(
                requirement, self.knowledge, state["feature_key"], self.settings.fuzzy_threshold
            )
            context_text = render_context(pack, self.knowledge, budget_tokens=int(budget * 0.6))
            vocabulary = render_vocabulary(pack, self.knowledge)

            plans = self._plan_one(requirement, feature_context, context_text)
            for plan in plans:
                tasks.append(
                    GenerationTask(
                        index=len(tasks),
                        requirement=requirement,
                        plan=plan,
                        context_text=context_text,
                        vocabulary=vocabulary,
                    )
                )

        self.store.save(
            f"plans_{state['sheet']}",
            [{"requirement": t.requirement.requirement_id, "plan": t.plan} for t in tasks],
        )
        logger.info("[sys5] sheet %s: planned %d test case(s)", state["sheet"], len(tasks))
        return {"tasks": tasks}

    def _plan_one(self, requirement, feature_context, context_text) -> list[TestCasePlan]:
        """One planning call, with a defined fallback if it fails.

        A planning failure must not silently drop a requirement, so a single-case plan
        is synthesised from the requirement text — the run continues and the gap is
        visible in the output rather than being an absent test case nobody notices.
        """
        if self.caller is None:
            return [_fallback_plan(requirement)]

        prompt = planner_prompt(
            requirement, feature_context, context_text, self.settings.max_cases_per_requirement
        )
        try:
            response = self.caller.invoke(
                PlanResponse, self.system, prompt, tag=f"plan:{requirement.requirement_id}"
            )
        except Exception as exc:  # noqa: BLE001 - one requirement must not kill the run
            logger.error(
                "[sys5] planning failed for %s (%s); falling back to a single case",
                requirement.requirement_id,
                exc,
            )
            return [_fallback_plan(requirement)]

        plans = [TestCasePlan.model_validate(c.model_dump()) for c in response.test_cases]
        if not plans:
            logger.warning(
                "[sys5] planner returned no cases for %s; falling back",
                requirement.requirement_id,
            )
            return [_fallback_plan(requirement)]

        plans = self._cap_plans(plans, requirement.requirement_id)

        logger.info(
            "[sys5]   %s -> %d case(s): %s",
            requirement.requirement_id,
            len(plans),
            "; ".join(p.aspect for p in plans),
        )
        return plans

    def _cap_plans(self, plans: list[TestCasePlan], requirement_id: str) -> list[TestCasePlan]:
        """Hard backstop on case count, independent of what the planner returned.

        The prompt asks for at most ``max_cases_per_requirement`` already, but a model
        must never be trusted to enforce its own limit, so this keeps the highest-value
        cases (priority, then boundary cases) if it returns more anyway.
        """
        limit = self.settings.max_cases_per_requirement
        if len(plans) <= limit:
            return plans

        def rank(indexed: tuple[int, TestCasePlan]) -> tuple[str, int, int]:
            position, plan = indexed
            priority = (plan.priority or "P1").strip().upper() or "P1"
            is_normal = 0 if plan.test_type == "Boundary" else 1
            return (priority, is_normal, position)

        ordered = sorted(enumerate(plans), key=rank)
        kept = sorted(ordered[:limit], key=lambda item: item[0])
        dropped = [plan.aspect for _, plan in ordered[limit:]]

        logger.warning(
            "[sys5]   %s: planner returned %d case(s), capped to %d; dropped: %s",
            requirement_id,
            len(plans),
            limit,
            "; ".join(dropped),
        )
        return [plan for _, plan in kept]

    def fan_out(self, state) -> list[Send] | list[str]:
        """One ``Send`` branch per planned test case.

        A ``Send`` payload replaces the branch's state rather than merging into it, so
        everything ``generate_case`` needs travels in the payload.
        """
        tasks = state.get("tasks") or []
        if not tasks:
            # No plans: skip straight to rendering so the run still produces a workbook
            # (with its cover and stubs) rather than ending with no output at all.
            logger.warning("[sys5] sheet %s produced no test-case plans", state["sheet"])
            return ["render"]

        return [
            Send(
                "generate_case",
                {
                    "task": task,
                    "sheet": state["sheet"],
                    "identity": state["identity"],
                    "feature_context": state["feature_context"],
                },
            )
            for task in tasks
        ]

    def generate_case(self, state) -> dict:
        """Generate, validate and repair one test case."""
        task = state["task"]
        identity: FeatureIdentity = state["identity"]
        feature_context: FeatureContext = state["feature_context"]

        # Derived from the task, not a shared counter: branches run in parallel, and
        # `render` renumbers into sheet order once they have all completed anyway.
        case_index = task.index + 1

        case = self._generate(task, identity, feature_context, case_index)
        if case is None:
            return {"generated": []}

        case, result = self._validate_and_repair(case, task, identity, case_index)
        case.issues = list(result.issues)

        if result.ok:
            logger.info("[sys5]   %s ok (%d steps)", case.tc_id, len(case.steps))
        else:
            logger.warning(
                "[sys5]   %s kept with %d unresolved issue(s): %s",
                case.tc_id,
                len(result.issues),
                result.codes(),
            )
            _mark_unresolved(case, result)

        return {"generated": [case]}

    def _steps_from_llm(self, prompt: str, tag: str) -> list[GeneratedStep] | None:
        """Call the model for a set of steps; ``None`` on any failure so the caller can fall back."""
        try:
            response = self.caller.invoke(StepsResponse, self.system, prompt, tag=tag)
        except Exception as exc:  # noqa: BLE001
            logger.error("[sys5] %s failed: %s", tag, exc)
            return None
        if not response.steps:
            logger.warning("[sys5] %s returned no steps", tag)
            return None
        return response.steps

    def _generate(
        self,
        task,
        identity: FeatureIdentity,
        feature_context: FeatureContext,
        case_index: int,
    ) -> TestCase | None:
        """The first generation attempt for one planned case."""
        if self.caller is None:
            return None

        prompt = generator_prompt(
            task.requirement,
            feature_context,
            task.plan,
            task.context_text,
            task.vocabulary,
            self.profile.start_marker,
            self.profile.end_marker,
        )
        steps = self._steps_from_llm(prompt, tag=f"generate:{task.plan.aspect}")
        if steps is None:
            return None

        return build_test_case(
            steps, task.plan, task.requirement, identity, self.profile, case_index
        )

    def _validate_and_repair(
        self,
        case: TestCase,
        task,
        identity: FeatureIdentity,
        case_index: int,
    ) -> tuple[TestCase, ValidationResult]:
        """Validate, then spend the correction budget on what the model must fix.

        ``max_validation_attempts`` bounds how many times a case is validated and
        ``max_correction_attempts`` how many repair calls are made; the loop ends as
        soon as a case is clean.
        """
        scoped_names = set(task.vocabulary)
        result = validate_case(case, self.index, self.profile, task.plan, scoped_names)
        corrections = 0

        for _ in range(max(0, self.settings.max_validation_attempts - 1)):
            if result.ok or corrections >= self.settings.max_correction_attempts:
                break
            if self.caller is None:
                break

            corrections += 1
            logger.info(
                "[sys5]   repairing %s (attempt %d): %s",
                case.tc_id,
                corrections,
                result.codes(),
            )
            repaired = self._repair(case, result, task, identity, case_index)
            if repaired is None:
                break
            case = repaired
            result = validate_case(case, self.index, self.profile, task.plan, scoped_names)

        return case, result

    def _repair(
        self,
        case: TestCase,
        result: ValidationResult,
        task,
        identity: FeatureIdentity,
        case_index: int,
    ) -> TestCase | None:
        prompt = repair_prompt(case, result, task.vocabulary)
        steps = self._steps_from_llm(prompt, tag=f"repair:{case.tc_id}")
        if steps is None:
            return None

        return build_test_case(
            steps, task.plan, task.requirement, identity, self.profile, case_index
        )

    def render(self, state) -> dict:
        """Write the workbook for this sheet."""
        cases: list[TestCase] = sorted(state.get("generated") or [], key=lambda c: c.tc_id)
        # Ids are assigned as branches complete, which is non-deterministic under
        # parallelism; renumber so the sheet always reads 01, 02, 03 in order.
        for position, case in enumerate(cases, start=1):
            case.tc_id = self.profile.test_case_id(position, state["identity"].label)

        summary = RunSummary(
            sheet=state["sheet"],
            feature_title=state["identity"].title,
            requirements_scanned=len(state.get("rows") or []),
            requirements_selected=len(state.get("requirements") or []),
            test_cases_planned=len(state.get("tasks") or []),
            test_cases_generated=len(cases),
            test_cases_valid=sum(1 for c in cases if c.is_valid),
            test_cases_with_issues=sum(1 for c in cases if not c.is_valid),
            llm_calls=self.caller.calls if self.caller else 0,
        )

        context = RenderContext(
            profile=self.profile,
            identity=state["identity"],
            feature=state["feature_context"],
            sheet=state["sheet"],
            project_name=self.settings.project_name,
            version=self.settings.version,
            username=self.settings.username,
            generated_at=datetime.now(),
            summary=summary,
            describe=self.index.describe,
            available_variants=tuple(self.settings.available_variants),
        )

        destination = self.settings.output_dir / self.template.filename(context)
        result = render_workbook(self.template, cases, context, destination)
        summary.output_path = str(result.path)

        self.store.save(f"generated_{state['sheet']}", cases)
        self.store.save(
            f"summary_{state['sheet']}",
            {"summary": summary, "issues": summarise([ValidationResult(issues=c.issues) for c in cases])},
        )
        logger.info("[sys5] %s", summary.render())

        return {"summary": summary, "output_path": str(result.path)}

    # ------------------------------------------------------------------ graph
    def build(self):
        """Compile the graph."""
        from .state import Sys5State

        graph = StateGraph(Sys5State)
        graph.add_node("select", self.select)
        graph.add_node("plan", self.plan, retry_policy=NODE_RETRY)
        graph.add_node("generate_case", self.generate_case, retry_policy=NODE_RETRY)
        graph.add_node("render", self.render)

        graph.add_edge(START, "select")
        graph.add_edge("select", "plan")
        graph.add_conditional_edges("plan", self.fan_out, ["generate_case", "render"])
        graph.add_edge("generate_case", "render")
        graph.add_edge("render", END)

        return graph.compile(name="sys5")


def _fallback_plan(requirement) -> TestCasePlan:
    """A single-case plan used when the planner is unavailable or fails."""
    return TestCasePlan(
        aspect=requirement.heading or requirement.requirement_id,
        description=requirement.text[:400],
        ranges_or_boundaries=[],
        priority=requirement.priority or "P1",
        variant=requirement.variant or "",
    )


def _mark_unresolved(case: TestCase, result: ValidationResult) -> None:
    """Flag a case that exhausted its repair budget, in the sheet itself.

    Shipping it silently would be worse than shipping it marked: a reviewer needs to see
    which cases still need a human, and the surrounding steps are still useful work.
    """
    codes = ", ".join(result.codes())
    if case.steps:
        case.steps[0].remark = (
            f"[VALIDATION_FAILED: {codes}] {case.steps[0].remark}".strip()
        )


def prepare_sheet_run(
    inventory: InputInventory, sheet: str
) -> SheetRun:
    """Parse one requirement sheet into the run's starting state."""
    classified = next(s for s in inventory.requirement_sheets() if s.sheet == sheet)
    identity, feature_context, rows = requirements_source.parse_requirement_sheet(
        classified.path, classified.sheet
    )
    return SheetRun(
        sheet=sheet,
        feature_key=classified.feature,
        identity=identity,
        feature_context=feature_context,
        rows=rows,
    )


__all__ = ["Sys5Pipeline", "SheetRun", "prepare_sheet_run", "build_inventory", "load_knowledge_base"]
