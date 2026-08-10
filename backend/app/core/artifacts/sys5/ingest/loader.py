"""Drives the source parsers from a classified inventory."""

from __future__ import annotations

import logging

from ..models import KnowledgeBase
from .registry import InputInventory, SourceKind
from .sources import (
    app_parameters,
    comm_matrix,
    command_list,
    compound_commands,
    configuration_file,
    io_signals,
    keyword_library,
)

logger = logging.getLogger(__name__)


def load_knowledge_base(inventory: InputInventory) -> KnowledgeBase:
    """Parse every supporting sheet in the inventory into one knowledge base.

    A parser that raises is logged and skipped: one malformed supporting sheet degrades
    the traceable context but must not abort a run, and the validator will reject any
    step that relies on the data that failed to load.
    """
    knowledge = KnowledgeBase()

    handlers = {
        SourceKind.COMM_MATRIX: lambda s: knowledge.can_signals.extend(
            comm_matrix.parse(s.path, s.sheet)
        ),
        SourceKind.IO_SIGNALS: lambda s: knowledge.io_signals.extend(
            io_signals.parse(s.path, s.sheet)
        ),
        SourceKind.APP_PARAMETERS: lambda s: knowledge.app_parameters.extend(
            app_parameters.parse(s.path, s.sheet)
        ),
        SourceKind.COMMAND_LIST: lambda s: knowledge.commands.extend(
            command_list.parse(s.path, s.sheet)
        ),
        SourceKind.COMPOUND_SET: lambda s: knowledge.compounds.extend(
            compound_commands.parse(s.path, s.sheet, category="set")
        ),
        SourceKind.COMPOUND_VERIFY: lambda s: knowledge.compounds.extend(
            compound_commands.parse(s.path, s.sheet, category="verify")
        ),
        SourceKind.LIBRARY_LIST: lambda s: knowledge.libraries.extend(
            keyword_library.parse_library_list(s.path, s.sheet)
        ),
        SourceKind.KEYWORD_DESCRIPTION: lambda s: knowledge.notes.setdefault(
            s.label, []
        ).extend(keyword_library.parse_keyword_description(s.path, s.sheet)),
        SourceKind.TOLERANCES: lambda s: knowledge.tolerances.extend(
            configuration_file.parse_tolerances(s.path, s.sheet)
        ),
        SourceKind.CONFIGURATIONS: lambda s: knowledge.configurations.extend(
            configuration_file.parse_configurations(s.path, s.sheet)
        ),
        SourceKind.MODEL_INPUT_MAPPING: lambda s: knowledge.model_signals.extend(
            configuration_file.parse_model_input_mapping(s.path, s.sheet)
        ),
        SourceKind.GLOBAL_VARIABLES: lambda s: knowledge.global_variables.extend(
            configuration_file.parse_global_variables(s.path, s.sheet)
        ),
    }

    for sheet in inventory.sheets:
        handler = handlers.get(sheet.kind)
        if handler is None:
            continue
        try:
            handler(sheet)
        except Exception as exc:  # noqa: BLE001 - one bad sheet must not kill the run
            logger.warning("[sys5] failed to parse %s (%s): %s", sheet.label, sheet.kind, exc)

    logger.info("[sys5] knowledge base: %s", knowledge.stats())
    return knowledge
