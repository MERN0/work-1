"""Extensible formatter registry (ARCHITECTURE.md Sec4.5). Adding a new output
format later = new OutputFormatter subclass + one FORMATTERS entry, no core
pipeline changes."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from schemas import ConfigurableParameterEntry, ItemListEntry, TestCase, TestPatternFactor, TestPatternRow, TraceabilityEntry


class OutputFormatter(ABC):
    @abstractmethod
    def write(
        self,
        test_cases: list[TestCase],
        traceability: list[TraceabilityEntry],
        item_list_entries: list[ItemListEntry],
        test_pattern_factors: list[TestPatternFactor],
        test_pattern_rows: list[TestPatternRow],
        configurable_parameters: list[ConfigurableParameterEntry],
        path: Path,
        run_meta: dict,
    ) -> None: ...
