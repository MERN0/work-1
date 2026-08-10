"""SYS5 artifact generator.

Generates SYS5 System Qualification Test Cases from SYS2 System Requirements and the
project's supporting workbooks (signals, commands, compound commands, libraries,
tolerances, configuration).

The public surface is unchanged from the previous dummy implementation —
``generate(config) -> str`` — so existing callers need no modification. A single-feature
run returns the path of the generated ``.xlsx``; a run over every feature sheet returns a
``.zip`` of them.

Everything the model writes is checked against a vocabulary index built from the input
sheets, so a signal, command, library or tolerance that does not exist in the source
data cannot reach the output.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from .graph import Sys5Pipeline, prepare_sheet_run
from .indexing import VocabularyIndex
from .ingest import build_inventory, load_knowledge_base
from .llm import LLMNotConfiguredError, StructuredCaller, build_chat_model
from .output import UnknownTemplateError, available, resolve
from .projects import resolve as resolve_profile
from .settings import Sys5Settings
from .utils.io import discover_workbooks, ensure_dir, zip_files
from .utils.json_store import JsonStore, new_run_id

logger = logging.getLogger(__name__)


class Sys5Error(RuntimeError):
    """Raised when a run cannot proceed."""


def generate(config: dict) -> str:
    """Generate SYS5 test cases and return the path of the produced artifact.

    Accepts the standardised SME6-compatible config payload. Recognised keys beyond the
    common ones: ``req_filename``, ``req_sheet_name`` (empty means every feature sheet),
    ``output_template``, ``project_profile``, ``req_keywords``, ``fuzzy_threshold``,
    ``max_validation_attempts``, ``max_correction_attempts`` and the ``llm_*`` overrides.
    """
    settings = Sys5Settings.from_config(config)
    logging.getLogger("app.core.artifacts.sys5").setLevel(settings.log_level)

    logger.info(
        "[sys5] generate(): project=%s user=%s version=%s domain=%s artifact=%s "
        "model=%s template=%s sheet=%r",
        settings.project_name,
        settings.username,
        settings.version,
        settings.domain,
        settings.artifact,
        settings.llm.model,
        settings.output_template or "(profile default)",
        settings.req_sheet_name or "(all)",
    )

    if settings.agent_chain:
        names = [a.get("agent_name", "?") for a in settings.agent_chain]
        logger.info("[sys5] agent_chain: %s", names)

    profile = resolve_profile(
        settings.project_profile, settings.project_name, settings.domain
    )
    logger.info("[sys5] project profile: %s", profile.name)

    # Resolve the output template before anything expensive happens: a typo here must
    # cost milliseconds, not a full generation pass.
    template_name = settings.output_template or profile.default_output_template
    try:
        template = resolve(template_name)
    except UnknownTemplateError as exc:
        raise Sys5Error(str(exc)) from exc
    logger.info("[sys5] output template: %s (available: %s)", template.name, ", ".join(available()))

    if not settings.req_keywords:
        settings.req_keywords = list(profile.req_keywords)

    ensure_dir(settings.output_dir)
    store = JsonStore(settings.work_dir, new_run_id("sys5"), settings.keep_intermediates)
    logger.info("[sys5] intermediates: %s", store.run_dir if store.enabled else "(disabled)")

    # ---------------------------------------------------------------- ingest
    workbooks = discover_workbooks(settings.input_dir, settings.uploaded_files)
    if not workbooks:
        raise Sys5Error(
            f"no .xlsx inputs found in {settings.input_dir} "
            f"(uploaded_files={settings.uploaded_files})"
        )
    logger.info("[sys5] %d input workbook(s): %s", len(workbooks), [p.name for p in workbooks])

    inventory = build_inventory(workbooks, settings.req_filename)
    requirement_sheets = inventory.requirement_sheets()
    if not requirement_sheets:
        raise Sys5Error(
            "no requirement sheets recognised in the input workbooks. Checked: "
            f"{[p.name for p in workbooks]}. Set `req_filename` to the requirements file "
            "if it is ambiguous."
        )

    knowledge = load_knowledge_base(inventory)
    index = VocabularyIndex.from_knowledge(knowledge)
    if not len(index):
        logger.warning(
            "[sys5] the vocabulary index is empty; every generated step will fail "
            "validation. Are the supporting workbooks present in %s?",
            settings.input_dir,
        )
    store.save("inventory", {
        "classified": [f"{s.label} -> {s.kind}" for s in inventory.sheets],
        "skipped": inventory.skipped,
        "knowledge": knowledge.stats(),
        "vocabulary_size": len(index),
    })

    sheets = _select_sheets(inventory, settings.req_sheet_name)
    logger.info("[sys5] generating for sheet(s): %s", sheets)

    # ------------------------------------------------------------------- llm
    caller = _build_caller(settings)

    pipeline = Sys5Pipeline(
        settings=settings,
        profile=profile,
        template=template,
        knowledge=knowledge,
        index=index,
        caller=caller,
        store=store,
    )
    graph = pipeline.build()

    # ------------------------------------------------------------------- run
    produced: list[Path] = []
    for sheet in sheets:
        run = prepare_sheet_run(inventory, sheet)
        logger.info("[sys5] === sheet %s: %s ===", sheet, run.identity.title)

        final = graph.invoke(
            {
                "sheet": run.sheet,
                "feature_key": run.feature_key,
                "identity": run.identity,
                "feature_context": run.feature_context,
                "rows": run.rows,
                "generated": [],
            },
            {"recursion_limit": 100, "max_concurrency": settings.llm.max_concurrency},
        )

        path = final.get("output_path")
        if path:
            produced.append(Path(path))

    if not produced:
        raise Sys5Error("no output was produced for any requirement sheet")

    return str(_finalise(produced, settings))


def _select_sheets(inventory, requested: str) -> list[str]:
    """Which requirement sheets to run over.

    An empty ``req_sheet_name`` means every feature sheet; a named one must exist, and
    naming a sheet that is not there is an error rather than a silently empty run.
    """
    available_sheets = [s.sheet for s in inventory.requirement_sheets()]
    if not requested:
        return available_sheets

    for sheet in available_sheets:
        if sheet.strip().lower() == requested.strip().lower():
            return [sheet]

    raise Sys5Error(
        f"requirement sheet {requested!r} not found. Available: {', '.join(available_sheets)}"
    )


def _build_caller(settings: Sys5Settings) -> StructuredCaller | None:
    """Build the structured-output caller, or ``None`` when the LLM is unavailable."""
    try:
        model = build_chat_model(settings.llm)
    except LLMNotConfiguredError as exc:
        raise Sys5Error(
            f"{exc} Set them in the environment (see backend/.env.example) or pass them "
            "in the config."
        ) from exc

    return StructuredCaller(model, method=settings.llm.structured_method)


def _finalise(produced: list[Path], settings: Sys5Settings) -> Path:
    """Return the single workbook, or zip several of them.

    Only the workbook (or the zip) is left in the caller's output directory; every
    intermediate JSON stays in the run's working directory.
    """
    if len(produced) == 1:
        logger.info("[sys5] done: %s", produced[0])
        return produced[0]

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive = settings.output_dir / f"sys5_{settings.project_name}_{stamp}.zip"
    zip_files(produced, archive)
    logger.info("[sys5] done: %d workbooks zipped into %s", len(produced), archive)
    return archive
