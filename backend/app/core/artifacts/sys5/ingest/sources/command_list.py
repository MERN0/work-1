"""Parser for the *Command List* workbook."""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import Command, Provenance
from ..workbook import load_sheet

logger = logging.getLogger(__name__)

HEADERS = [
    "SL.No",
    "Type",
    "Command name",
    "Message Name",
    "Signal Description",
    "Signal Name",
    "Index (Hex)",
    "SubIndex (Hex)",
    "Decimal",
]


def parse(path: Path, sheet: str) -> list[Command]:
    """Read the callable command names used in ``Set``/``Verify`` steps.

    ``Command name`` (e.g. ``CAN_Main_DispSpeed``) is the name a test step uses;
    ``Signal Name`` (e.g. ``Disp_Rx1_DispSpeed``) is how the command is linked back to a
    CAN signal during tracing, and is registered as an alias.
    """
    table = load_sheet(path, sheet, HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    commands: list[Command] = []
    for row in table.rows:
        name = row.get("Command name", "CommandName", "Command")
        if not name:
            continue

        signal_name = row.get("Signal Name", "SignalName")
        commands.append(
            Command(
                name=name,
                aliases=[a for a in (signal_name,) if a],
                description=row.get("Signal Description", "SignalDescription", "Description"),
                command_type=row.get("Type"),
                message_name=row.get("Message Name", "MessageName"),
                signal_name=signal_name,
                index_hex=row.get("Index (Hex)", "Index(Hex)", "Index"),
                subindex_hex=row.get("SubIndex (Hex)", "SubIndex(Hex)", "SubIndex"),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d commands", path.name, sheet, len(commands))
    return commands
