"""Filesystem helpers for locating inputs and packaging outputs."""

from __future__ import annotations

import logging
import zipfile
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

#: Extensions we are willing to open as a source workbook.
EXCEL_SUFFIXES = frozenset({".xlsx", ".xlsm", ".xltx"})

#: Files Excel and OneDrive leave behind that must never be parsed.
_IGNORED_PREFIXES = ("~$", ".~")


def discover_workbooks(input_dir: Path, uploaded: Iterable[str] = ()) -> list[Path]:
    """Every candidate workbook for a run, de-duplicated and sorted.

    Combines a recursive scan of ``input_dir`` with any explicitly uploaded paths, so a
    caller may pass files that live outside the input directory.
    """
    found: dict[Path, None] = {}

    if input_dir and input_dir.is_dir():
        for path in sorted(input_dir.rglob("*")):
            if _is_workbook(path):
                found.setdefault(path.resolve(), None)

    for raw in uploaded:
        path = Path(raw).expanduser()
        if not path.is_absolute() and input_dir:
            candidate = input_dir / path
            path = candidate if candidate.exists() else path
        if _is_workbook(path):
            found.setdefault(path.resolve(), None)
        elif raw:
            logger.warning("[sys5] uploaded file is not a readable workbook: %s", raw)

    return list(found)


def _is_workbook(path: Path) -> bool:
    return (
        path.is_file()
        and path.suffix.lower() in EXCEL_SUFFIXES
        and not path.name.startswith(_IGNORED_PREFIXES)
    )


def zip_files(paths: Iterable[Path], destination: Path) -> Path:
    """Zip ``paths`` (flat, by basename) into ``destination`` and return it."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in paths:
            if path.is_file():
                archive.write(path, arcname=path.name)
    return destination


def ensure_dir(path: Path) -> Path:
    """Create ``path`` (and parents) if missing, returning it."""
    path.mkdir(parents=True, exist_ok=True)
    return path
