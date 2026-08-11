"""The Vocabulary Index — the single authority on which names may appear in a test step.

Built as the union of every name found in every input sheet: I/O logical names, CAN
logical and bus names, command names, ``MDL_*`` model signals, compound-command names,
library function names, ``Config_Tol_*`` names, app-parameter names and global
variables. A name is legal if and only if it is in here.

This one object serves two roles that must never diverge: it is the menu handed to the
LLM, and it is the oracle the validator consults. Because both read the same structure,
a step the model was allowed to write is a step the validator will accept — and a
hallucinated name has nowhere to hide.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process

from ..models import KnowledgeBase, KnowledgeRecord, VocabKind
from ..utils.text import normalize

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class VocabularyEntry:
    """One legal name and the record(s) it refers to."""

    name: str
    records: list[KnowledgeRecord] = field(default_factory=list)

    @property
    def kinds(self) -> set[VocabKind]:
        return {r.kind for r in self.records}

    @property
    def primary(self) -> KnowledgeRecord:
        return self.records[0]


class VocabularyIndex:
    """Case- and punctuation-insensitive lookup over every legal name."""

    def __init__(self) -> None:
        self._by_key: dict[str, VocabularyEntry] = {}
        self._by_kind: dict[VocabKind, list[KnowledgeRecord]] = defaultdict(list)

    # ------------------------------------------------------------------ build
    @classmethod
    def from_knowledge(cls, knowledge: KnowledgeBase) -> VocabularyIndex:
        """Index every record of a knowledge base under all of its names."""
        index = cls()
        for record in knowledge.records():
            index.add(record)
        logger.info(
            "[sys5] vocabulary index: %d distinct names across %d records",
            len(index._by_key),
            sum(len(v) for v in index._by_kind.values()),
        )
        return index

    def add(self, record: KnowledgeRecord) -> None:
        """Register a record under its name and every alias."""
        self._by_kind[record.kind].append(record)
        for name in record.all_names():
            key = normalize(name)
            if not key:
                continue
            entry = self._by_key.get(key)
            if entry is None:
                self._by_key[key] = VocabularyEntry(name=name, records=[record])
            elif record not in entry.records:
                entry.records.append(record)

    # ----------------------------------------------------------------- lookup
    def __len__(self) -> int:
        return len(self._by_key)

    def __contains__(self, name: object) -> bool:
        return normalize(name) in self._by_key

    def resolve(self, name: str) -> VocabularyEntry | None:
        """The entry for ``name``, or ``None`` when the name is not legal."""
        return self._by_key.get(normalize(name))

    def is_legal(self, name: str, kinds: set[VocabKind] | None = None) -> bool:
        """True when ``name`` exists, optionally restricted to certain record kinds."""
        entry = self.resolve(name)
        if entry is None:
            return False
        return True if kinds is None else bool(entry.kinds & kinds)

    def describe(self, name: str) -> str:
        """The description of a legal name, or ``""`` when unknown or undocumented.

        The single point of contact output templates use for descriptions, so a
        template never needs the raw :class:`KnowledgeRecord` types to render a
        human-readable "what is this" column.
        """
        entry = self.resolve(name)
        if entry is None:
            return ""
        for record in entry.records:
            if record.description:
                return record.description
        return ""

    def of_kind(self, *kinds: VocabKind) -> list[KnowledgeRecord]:
        """Every record of the given kinds."""
        result: list[KnowledgeRecord] = []
        for kind in kinds:
            result.extend(self._by_kind.get(kind, []))
        return result

    def names(self, kinds: set[VocabKind] | None = None) -> list[str]:
        """All legal names, optionally filtered by kind, in insertion order."""
        return [
            entry.name
            for entry in self._by_key.values()
            if kinds is None or (entry.kinds & kinds)
        ]

    # ------------------------------------------------------------- suggestion
    def suggest(self, name: str, limit: int = 3, threshold: int = 70) -> list[str]:
        """Closest legal names to an illegal one.

        Fed into the repair prompt so a correction round has something concrete to aim
        at instead of being told only that the name was wrong.
        """
        if not self._by_key:
            return []
        key = normalize(name)
        if not key:
            return []
        matches = process.extract(
            key, list(self._by_key.keys()), scorer=fuzz.WRatio, limit=limit
        )
        return [self._by_key[m].name for m, score, _ in matches if score >= threshold]
