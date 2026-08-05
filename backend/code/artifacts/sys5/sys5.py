#!/usr/bin/env python3
"""SYS5 qualification test case generator -- CLI entry point.

Directory convention: `backend/` is the project root; this file
(`backend/code/artifacts/sys5/sys5.py`) is where execution starts.

    python3 sys5.py --requirements samples/sample_requirements.xlsx --domain forklift

Every stage of the run prints to the console (and to state/run_<id>_logs/run.log)
via logging_setup -- preprocessing counts, each LangGraph node's start/done/duration,
per-cluster progress, verification pass/fail, and the final output file's checksum.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Allow `python sys5.py` to import its sibling modules (schemas, subagents, ...)
# as flat top-level packages regardless of the caller's cwd.
sys.path.insert(0, str(Path(__file__).parent))

import checkpoint_store
from config_loader import load_run_config
from formats.default_formatter import FORMATTERS
from graph import build_graph
from llm import get_llm, is_mock
from logging_setup import configure_logging, get_logger, log_data, stage
from preprocessing import build_supporting_doc_registry, filter_requirement_rows

SYS5_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SYS5_DIR / "output"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SYS5 qualification test case generator")
    p.add_argument("--requirements", nargs="+", required=True, help="SYS2 requirements workbook(s) (xlsx)")
    p.add_argument("--supporting-docs", nargs="*", default=[], help="Optional supporting-doc workbook(s) (xlsx)")
    p.add_argument("--domain", required=True, choices=["bcm", "telematics", "chassis", "adas", "powertrain", "forklift"],
                    help="Run domain param (forklift included provisionally -- see ARCHITECTURE.md Sec8 Q1)")
    p.add_argument("--config-dir", default=str(SYS5_DIR / "config"), help="Config directory (default: ./config)")
    p.add_argument("--output-format", default="default", choices=list(FORMATTERS.keys()))
    p.add_argument("--project", default="default", help="Project guideline manifest key")
    p.add_argument("--output", default=None, help="Output xlsx path (default: output/<run_id>.xlsx)")
    p.add_argument("--run-id", default=None, help="Resume an existing run by ID; omit to start a fresh timestamped run")
    p.add_argument("--document-no", default=None)
    p.add_argument("--version", default="1.0")
    p.add_argument("--mock-llm", action="store_true", help="Force deterministic mock LLM output (no real endpoint call)")
    p.add_argument("-v", "--verbose", action="store_true", help="DEBUG-level console output")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_id = args.run_id or time.strftime("%Y%m%d_%H%M%S")

    state_dir = SYS5_DIR / "state"
    log_dir = state_dir / f"run_{run_id}_logs"
    log = configure_logging(verbose=args.verbose, run_dir=log_dir)
    log = get_logger("sys5")

    if args.mock_llm:
        os.environ["SYS5_MOCK_LLM"] = "1"

    log.info("=" * 78)
    log.info("SYS5 qualification test case generator -- run_id=%s", run_id)
    log.info("  requirements       : %s", args.requirements)
    log.info("  supporting_docs    : %s", args.supporting_docs or "(none)")
    log.info("  domain             : %s", args.domain)
    log.info("  output_format      : %s", args.output_format)
    log.info("  config_dir         : %s", args.config_dir)
    log.info("  log file           : %s", log_dir / "run.log")
    log.info("=" * 78)

    try:
        with stage(log, "load_config"):
            config = load_run_config(Path(args.config_dir), domain=args.domain, output_format_name=args.output_format, project=args.project)

        requirement_paths = [Path(p) for p in args.requirements]
        supporting_paths = [Path(p) for p in args.supporting_docs]

        requirements = filter_requirement_rows(requirement_paths, config)
        if not requirements:
            log.error("No requirement rows matched the sys-qualification filter -- nothing to generate. Aborting.")
            return 1
        requirements_by_id = {r.requirement_id: r for r in requirements}

        supporting_docs = build_supporting_doc_registry(supporting_paths)

        run_state = checkpoint_store.load_or_create(run_id, args.domain, state_dir)
        run_state.requirement_workbooks = [str(p) for p in requirement_paths]
        run_state.supporting_doc_workbooks = [str(p) for p in supporting_paths]
        run_state.output_formats = [args.output_format]
        checkpoint_store.save(run_state, state_dir)

        llm = get_llm()
        log.info("LLM backend: %s%s", type(llm).__name__, " (MOCK MODE -- no real LLM calls)" if is_mock(llm) else "")

        app = build_graph()
        initial_state = {
            "config": config,
            "llm": llm,
            "run_state": run_state,
            "state_dir": state_dir,
            "requirements": requirements,
            "requirements_by_id": requirements_by_id,
            "supporting_docs": supporting_docs,
            "configurable_parameters": [],
            "verified_test_cases": [],
            "item_list_entries": [],
            "test_pattern_factors": [],
            "test_pattern_rows": [],
        }

        with stage(log, "graph.invoke", run_id=run_id):
            result = app.invoke(initial_state, config={"configurable": {"thread_id": run_id}})

        checkpoint_store.save(run_state, state_dir)

        test_cases = result["verified_test_cases"]
        traceability = result["traceability"]
        item_list_entries = result["item_list_entries"]
        test_pattern_factors = result["test_pattern_factors"]
        test_pattern_rows = result["test_pattern_rows"]

        output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_DIR / f"{run_id}_{args.output_format}.xlsx"
        run_meta = {
            "document_no": args.document_no or f"SYS5/{run_id}",
            "version": args.version,
            "created_by": "SYS5 AI Pipeline",
            "verified_by": "SYS5 AI Pipeline",
            "change_summary": f"Auto-generated by SYS5 AI Pipeline for run {run_id}",
            "revision_history": [{
                "revision_no": args.version, "change_description": f"Auto-generated for run {run_id}",
                "date": time.strftime("%Y-%m-%d"), "created_by": "SYS5 AI Pipeline",
                "approved_by": "SYS5 AI Pipeline", "description": f"{len(test_cases)} test case(s) generated",
            }],
        }

        formatter = FORMATTERS[args.output_format]
        with stage(log, "write_output", path=str(output_path)):
            formatter.write(
                test_cases, traceability, item_list_entries, test_pattern_factors, test_pattern_rows,
                result.get("configurable_parameters", []) or [], output_path, run_meta,
                output_format_config=config.output_format,
            )

        needs_review = [tc.id for tc in test_cases if tc.needs_review]
        log.info("=" * 78)
        log.info("RUN COMPLETE -- run_id=%s", run_id)
        log.info("  requirements filtered   : %d", len(requirements))
        log.info("  clusters                : %d", len(result["clusters"]))
        log.info("  test cases generated    : %d", len(test_cases))
        log.info("  needs_review            : %d %s", len(needs_review), needs_review or "")
        log.info("  output workbook         : %s", output_path)
        log.info("  checkpoint              : %s", checkpoint_store.checkpoint_path(run_id, state_dir))
        log.info("  run state summary       : %s", run_state.summary())
        log.info("=" * 78)
        log_data(log, "final_test_case_ids", [tc.id for tc in test_cases], level=20)

        return 0

    except Exception:
        log.exception("Run %s FAILED", run_id)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
