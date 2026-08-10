"""Parser for *Master Comm Matrix (CAN)*."""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import CanSignal, Provenance
from ..workbook import load_sheet
from ._common import feature_columns, marked_features

logger = logging.getLogger(__name__)

HEADERS = [
    "Signal ID",
    "Message Name",
    "Message IDs",
    "Logical Signal Name",
    "Signal Name",
    "Signal Description",
]


def parse(path: Path, sheet: str) -> list[CanSignal]:
    """Read every CAN signal, tagged with the features that mark it.

    Both the logical name (``Commanded_RPM``) and the bus name (``DrvL_Rx1_CmdSpd``) are
    legal ways to refer to the signal, so both are registered — the logical name as the
    record name and the bus name as an alias, alongside the signal id.
    """
    table = load_sheet(path, sheet, HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    columns = feature_columns(table)
    signals: list[CanSignal] = []

    for row in table.rows:
        signal_id = row.get("Signal ID", "SignalID")
        logical = row.get("Logical Signal Name", "LogicalSignalName")
        signal_name = row.get("Signal Name", "SignalName")
        if not (signal_id or logical or signal_name):
            continue

        signals.append(
            CanSignal(
                name=logical or signal_name or signal_id,
                aliases=[a for a in (signal_name, logical, signal_id) if a],
                description=row.get("Signal Description", "SignalDescription"),
                signal_id=signal_id,
                message_name=row.get("Message Name", "MessageName"),
                message_id=row.get("Message IDs", "Message ID", "MessageIDs"),
                logical_signal_name=logical,
                signal_name=signal_name,
                features=marked_features(row, columns),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info(
        "[sys5] %s[%s]: %d CAN signals, %d feature columns",
        path.name,
        sheet,
        len(signals),
        len(columns),
    )
    return signals
