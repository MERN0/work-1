"""Central logging configuration for the SYS5 pipeline.

Every stage of the pipeline (preprocessing, each LangGraph node, postprocessing)
logs through this module so a single run produces one readable, timestamped
narrative on stdout plus a persisted log file per run under state/<run_id>/run.log.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Iterator

_CONFIGURED = False
LOGGER_NAME = "sys5"


class _ConsoleFormatter(logging.Formatter):
    LEVEL_TAG = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO ",
        logging.WARNING: "WARN ",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "FATAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        record.leveltag = self.LEVEL_TAG.get(record.levelno, record.levelname)
        return super().format(record)


def configure_logging(verbose: bool = False, run_dir: Path | None = None) -> logging.Logger:
    """Configure the sys5 logger. Safe to call more than once; only the first
    call (per process) attaches handlers, later calls just return the logger.
    Everything logged goes to stdout AND, if run_dir is given, to run_dir/run.log.
    """
    global _CONFIGURED
    logger = logging.getLogger(LOGGER_NAME)
    if _CONFIGURED:
        return logger

    level = logging.DEBUG if verbose else logging.INFO
    logger.setLevel(logging.DEBUG)  # handlers filter; logger itself stays permissive

    fmt = "%(asctime)s | %(leveltag)s | %(name)-28s | %(message)s"
    datefmt = "%H:%M:%S"

    console = logging.StreamHandler(stream=sys.stdout)
    console.setLevel(level)
    console.setFormatter(_ConsoleFormatter(fmt, datefmt=datefmt))
    logger.addHandler(console)

    if run_dir is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(run_dir / "run.log", encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)  # file always gets everything
        file_handler.setFormatter(_ConsoleFormatter(fmt, datefmt=datefmt))
        logger.addHandler(file_handler)

    logger.propagate = False
    _CONFIGURED = True
    return logger


def get_logger(component: str) -> logging.Logger:
    """Child logger for a specific module/node, e.g. get_logger('clustering_agent')."""
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


@contextlib.contextmanager
def stage(logger: logging.Logger, name: str, **context: Any) -> Iterator[None]:
    """Wrap a pipeline stage so its start/end/duration/failure are always logged.

    Usage:
        with stage(log, "clustering_agent", cluster_count=12):
            ...
    """
    ctx_str = f" ({_format_context(context)})" if context else ""
    logger.info("START %s%s", name, ctx_str)
    t0 = time.perf_counter()
    try:
        yield
    except Exception:
        elapsed = time.perf_counter() - t0
        logger.exception("FAILED %s after %.2fs", name, elapsed)
        raise
    else:
        elapsed = time.perf_counter() - t0
        logger.info("DONE  %s in %.2fs", name, elapsed)


def _format_context(context: dict[str, Any]) -> str:
    return ", ".join(f"{k}={v}" for k, v in context.items())


def log_data(logger: logging.Logger, label: str, obj: Any, level: int = logging.DEBUG) -> None:
    """Pretty-print a structured object (dict/list/pydantic model) to the log.

    Kept at DEBUG by default to avoid flooding INFO-level console output with
    full payloads; pass level=logging.INFO to force it into the default view.
    """
    if hasattr(obj, "model_dump"):
        obj = obj.model_dump()
    try:
        text = json.dumps(obj, indent=2, default=str, ensure_ascii=False)
    except TypeError:
        text = str(obj)
    logger.log(level, "%s:\n%s", label, text)
