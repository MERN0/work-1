"""Persistence of intermediate artefacts.

Only the final workbook (or zip) may land in the caller's output directory; every
intermediate JSON goes to the run's working directory under the package, named so a
failed run can be inspected after the fact.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _default(obj: Any) -> Any:
    """Serialise the types our models use that ``json`` does not handle natively."""
    if isinstance(obj, BaseModel):
        return obj.model_dump(mode="json")
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    return str(obj)


class JsonStore:
    """Writes timestamped intermediates into a per-run working directory."""

    def __init__(self, work_dir: Path, run_id: str, enabled: bool = True) -> None:
        self.enabled = enabled
        self.run_dir = Path(work_dir) / run_id
        self.run_id = run_id
        if self.enabled:
            self.run_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, payload: Any) -> Path | None:
        """Write ``payload`` as ``<name>.json``. No-op when intermediates are disabled."""
        if not self.enabled:
            return None
        path = self.run_dir / f"{name}.json"
        try:
            path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False, default=_default),
                encoding="utf-8",
            )
        except OSError as exc:  # pragma: no cover - disk problems are environmental
            logger.warning("[sys5] could not write intermediate %s: %s", path, exc)
            return None
        logger.debug("[sys5] wrote intermediate %s", path)
        return path

    def save_text(self, name: str, text: str) -> Path | None:
        """Write raw text (used for prompt dumps when debugging)."""
        if not self.enabled:
            return None
        path = self.run_dir / name
        try:
            path.write_text(text, encoding="utf-8")
        except OSError as exc:  # pragma: no cover
            logger.warning("[sys5] could not write %s: %s", path, exc)
            return None
        return path


def new_run_id(prefix: str = "run") -> str:
    """A sortable, filesystem-safe run identifier."""
    return f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
