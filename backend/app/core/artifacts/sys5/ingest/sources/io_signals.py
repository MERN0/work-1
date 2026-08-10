"""Parser for *Master Input Output Signals*."""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import IoSignal, Provenance
from ..workbook import load_sheet
from ._common import feature_columns, marked_features

logger = logging.getLogger(__name__)

HEADERS = ["Signal ID", "Logical Signal Name", "Signal Type"]


def parse(path: Path, sheet: str) -> list[IoSignal]:
    """Read every I/O signal, tagged with the features that mark it.

    The logical name (``Accelerator_Sensor``) is the form used in ``Set``/``Verify``
    steps; the signal id is kept as an alias so a requirement referencing
    ``TMHC_SYSRS_IO0005`` still resolves.
    """
    table = load_sheet(path, sheet, HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    columns = feature_columns(table)
    signals: list[IoSignal] = []

    for row in table.rows:
        signal_id = row.get("Signal ID", "SignalID")
        logical = row.get("Logical Signal Name", "LogicalSignalName", "Signal Name")
        if not (signal_id or logical):
            continue

        signals.append(
            IoSignal(
                name=logical or signal_id,
                aliases=[a for a in (signal_id,) if a],
                description=row.get("Signal Description", "Description"),
                signal_id=signal_id,
                signal_type=row.get("Signal Type", "SignalType"),
                features=marked_features(row, columns),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info(
        "[sys5] %s[%s]: %d I/O signals, %d feature columns",
        path.name,
        sheet,
        len(signals),
        len(columns),
    )
    return signals
