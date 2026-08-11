"""The output-template contract.

The pipeline produces canonical :class:`TestCase` objects that know nothing about
columns or sheets. An :class:`OutputTemplate` is the only thing that does. Adding a new
customer layout means adding a template package — ingestion, tracing, generation and
validation are untouched, and the existing layout cannot regress because both are
exercised by the same contract test.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from ..models import FeatureContext, FeatureIdentity, RunSummary, TestCase
from ..projects import ProjectProfile


@dataclass(slots=True)
class ColumnSpec:
    """One output column.

    ``key`` exists because a layout may repeat a header — the TMHC sheet has two
    ``Units`` columns — so columns are addressed positionally by key, never by header.
    """

    key: str
    header: str
    width: int = 18
    wrap: bool = False
    #: Merge this column vertically across all rows of one test case.
    merge_per_case: bool = False
    #: Merge this column vertically across each phase block.
    merge_per_phase: bool = False


@dataclass(slots=True)
class SheetSpec:
    """One sheet in the output workbook."""

    key: str
    #: Literal tab name, or empty when :meth:`OutputTemplate.sheet_name` decides.
    name: str = ""
    #: Rendered but intentionally empty, pending a real template from the customer.
    stub: bool = False
    stub_note: str = ""


@dataclass(slots=True)
class RenderContext:
    """Everything a template needs beyond the test cases themselves."""

    profile: ProjectProfile
    identity: FeatureIdentity
    feature: FeatureContext
    sheet: str
    project_name: str = ""
    version: str = "v1.0"
    username: str = ""
    generated_at: datetime = field(default_factory=datetime.now)
    summary: RunSummary = field(default_factory=RunSummary)
    #: Looks up a legal name's description from the vocabulary index. Kept as a plain
    #: callable rather than the index itself, so a template gets descriptions without
    #: needing to know about `KnowledgeRecord`/`KnowledgeBase` internals.
    describe: Callable[[str], str] = lambda name: ""  # noqa: E731
    #: The project's full list of applicable variants, in canonical order (e.g. A1, A2,
    #: B, C1...). Used to order — not to invent — the variant columns a template shows.
    available_variants: tuple[str, ...] = ()

    @property
    def title(self) -> str:
        """The document title — the feature name from the requirement sheet."""
        return self.identity.title


@dataclass(slots=True)
class Row:
    """One rendered output row, addressed by column key.

    A row with no values renders as the blank separator between test cases.
    """

    values: dict[str, str] = field(default_factory=dict)
    #: The test case this row belongs to, used to drive per-case merging.
    case_index: int = -1
    phase: str = ""
    blank: bool = False


class OutputTemplate(ABC):
    """Maps canonical test cases onto a concrete workbook layout."""

    #: Registry key, e.g. ``"tmhc_v1"``.
    name: str = ""
    #: Human description, shown when an unknown template is requested.
    description: str = ""

    @abstractmethod
    def columns(self) -> list[ColumnSpec]:
        """The test-case sheet's columns, in order."""

    @abstractmethod
    def sheets(self) -> list[SheetSpec]:
        """Every sheet of the output workbook, in tab order."""

    @abstractmethod
    def emit_rows(self, cases: list[TestCase], context: RenderContext) -> Iterable[Row]:
        """Render the test cases as output rows."""

    def sheet_name(self, spec: SheetSpec, context: RenderContext) -> str:
        """Tab name for a sheet spec. Defaults to the literal name."""
        return spec.name or spec.key

    def filename(self, context: RenderContext) -> str:
        """Output filename for one requirement sheet."""
        stamp = context.generated_at.strftime("%Y%m%d_%H%M%S")
        return f"sys5_{context.sheet}_{stamp}.xlsx"

    def write_sheet(
        self, spec: SheetSpec, worksheet, context: RenderContext, cases: list[TestCase]
    ) -> bool:
        """Write a non-test-case sheet.

        ``cases`` is the same list :meth:`emit_rows` receives, so an auxiliary sheet can
        summarise or cross-reference the run without re-deriving it from the workbook.

        Return ``True`` when the template handled it; ``False`` to let the writer fall
        back to a stub. Templates override this for their cover page and any auxiliary
        sheet they have a real layout for.
        """
        return False

    def document_properties(self, context: RenderContext) -> dict[str, str]:
        """Workbook metadata."""
        return {
            "title": context.title,
            "creator": "SYS5 AI Pipeline",
            "description": f"SYS5 System Qualification Test Cases for {context.title}",
        }


@dataclass(slots=True)
class RenderResult:
    """What a render produced."""

    path: Path
    rows: int = 0
    cases: int = 0
