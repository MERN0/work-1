"""Canonical records for everything extracted from the supporting workbooks.

Every record carries its :class:`Provenance` so a generated test step can always be
traced back to the exact file/sheet/row it came from. That traceability is what makes
the "no hallucination" guarantee auditable rather than merely asserted.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Provenance(BaseModel):
    """Where a record was read from."""

    model_config = ConfigDict(frozen=True)

    file: str
    sheet: str
    row: int

    def __str__(self) -> str:  # pragma: no cover - trivial
        return f"{self.file}[{self.sheet}]:{self.row}"


class VocabKind(StrEnum):
    """The kind of thing a name in the vocabulary index refers to.

    Drives which grammar productions may legally reference the name.
    """

    IO_SIGNAL = "io_signal"
    CAN_SIGNAL = "can_signal"
    COMMAND = "command"
    MODEL_SIGNAL = "model_signal"
    COMPOUND = "compound"
    LIBRARY = "library"
    TOLERANCE = "tolerance"
    APP_PARAMETER = "app_parameter"
    GLOBAL_VARIABLE = "global_variable"


class KnowledgeRecord(BaseModel):
    """Base for every indexed record."""

    model_config = ConfigDict(extra="allow")

    kind: VocabKind
    name: str
    provenance: Provenance
    #: Extra names that refer to the same underlying entity (logical vs signal name,
    #: model-side vs bus-side naming). All of them are legal in a test step.
    aliases: list[str] = Field(default_factory=list)
    description: str = ""
    #: Feature numbers this record is marked against (the "○" columns).
    features: set[str] = Field(default_factory=set)

    def all_names(self) -> list[str]:
        """Every name under which this record may legally be referenced."""
        seen: dict[str, None] = {}
        for n in (self.name, *self.aliases):
            if n:
                seen.setdefault(n, None)
        return list(seen)


class IoSignal(KnowledgeRecord):
    """A row of *Master Input Output Signals*."""

    kind: VocabKind = VocabKind.IO_SIGNAL
    signal_id: str = ""
    signal_type: str = ""


class CanSignal(KnowledgeRecord):
    """A row of *Master Comm Matrix (CAN)*."""

    kind: VocabKind = VocabKind.CAN_SIGNAL
    signal_id: str = ""
    message_name: str = ""
    message_id: str = ""
    logical_signal_name: str = ""
    signal_name: str = ""


class Command(KnowledgeRecord):
    """A row of the *Command List* — the callable name used in Set/Verify steps."""

    kind: VocabKind = VocabKind.COMMAND
    command_type: str = ""
    message_name: str = ""
    signal_name: str = ""
    index_hex: str = ""
    subindex_hex: str = ""


class CompoundStep(BaseModel):
    """One line inside a compound command block."""

    keyword: str
    parameter: str = ""
    parameter_unit: str = ""
    expected: str = ""
    expected_unit: str = ""
    remark: str = ""


class CompoundCommand(KnowledgeRecord):
    """A ``Compound <Name>`` block from the compound-commands workbook."""

    kind: VocabKind = VocabKind.COMPOUND
    #: "set" or "verify" — which sheet the block came from.
    category: str = "set"
    steps: list[CompoundStep] = Field(default_factory=list)

    def summary(self) -> str:
        """One-line description used when the full body is too costly to include."""
        verbs = [s.keyword.split()[0] for s in self.steps if s.keyword]
        return f"{len(self.steps)} steps ({', '.join(dict.fromkeys(verbs))})"


class LibraryFunction(KnowledgeRecord):
    """A ``Lib_*`` entry from the keyword library's *Library List* sheet."""

    kind: VocabKind = VocabKind.LIBRARY
    #: The declared signature, e.g. ``Lib_Ramp Signal_Name(Start=X,Stop=X,Step=X,Time=X)``.
    signature: str = ""
    #: Parameter names parsed out of the signature, e.g. ``["Start", "Stop", "Step", "Time"]``.
    parameters: list[str] = Field(default_factory=list)
    #: True when the signature takes a signal name before the parenthesis.
    takes_signal: bool = False


class Tolerance(KnowledgeRecord):
    """A ``Config_Tol_*`` entry from the configuration workbook."""

    kind: VocabKind = VocabKind.TOLERANCE
    unit: str = ""
    value: str = ""
    tolerance_unit: str = ""
    positive: str = ""
    negative: str = ""


class AppParameter(KnowledgeRecord):
    """A row of *Master List - App Parameter*."""

    kind: VocabKind = VocabKind.APP_PARAMETER
    parameter_id: str = ""
    parameter_type: str = ""
    unit: str = ""
    valid_value: str = ""
    default_value: str = ""
    min_value: str = ""
    max_value: str = ""
    resolution: str = ""
    linked_requirement: str = ""


class ModelSignal(KnowledgeRecord):
    """A row of *Model_Input_Mapping* — an ``MDL_*`` signal and its legal inputs."""

    kind: VocabKind = VocabKind.MODEL_SIGNAL
    #: Values accepted in the "Test Case Input" column, e.g. ``["ON", "OFF"]``.
    allowed_inputs: list[str] = Field(default_factory=list)
    model_inputs: list[str] = Field(default_factory=list)


class ConfigurationEnum(BaseModel):
    """A row of the *Configurations* sheet: a signal and its enumerated values."""

    signal_name: str
    description: str = ""
    #: Parsed from e.g. ``0x00:H, 0x01:P, 0x02:S`` -> {"0x00": "H", ...}
    values: dict[str, str] = Field(default_factory=dict)
    raw: str = ""
    provenance: Provenance | None = None


class GlobalVariable(KnowledgeRecord):
    """A row of the *Global_Variables* sheet."""

    kind: VocabKind = VocabKind.GLOBAL_VARIABLE
    value: str = ""


class KnowledgeBase(BaseModel):
    """Everything parsed from the supporting workbooks for one run."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    io_signals: list[IoSignal] = Field(default_factory=list)
    can_signals: list[CanSignal] = Field(default_factory=list)
    commands: list[Command] = Field(default_factory=list)
    compounds: list[CompoundCommand] = Field(default_factory=list)
    libraries: list[LibraryFunction] = Field(default_factory=list)
    tolerances: list[Tolerance] = Field(default_factory=list)
    app_parameters: list[AppParameter] = Field(default_factory=list)
    model_signals: list[ModelSignal] = Field(default_factory=list)
    configurations: list[ConfigurationEnum] = Field(default_factory=list)
    global_variables: list[GlobalVariable] = Field(default_factory=list)
    #: Free-text notes captured above header rows, keyed by "file[sheet]".
    notes: dict[str, list[str]] = Field(default_factory=dict)

    def records(self) -> list[KnowledgeRecord]:
        """Every indexable record, flattened."""
        return [
            *self.io_signals,
            *self.can_signals,
            *self.commands,
            *self.compounds,
            *self.libraries,
            *self.tolerances,
            *self.app_parameters,
            *self.model_signals,
            *self.global_variables,
        ]

    def stats(self) -> dict[str, int]:
        """Counts per record type, for run logging."""
        return {
            "io_signals": len(self.io_signals),
            "can_signals": len(self.can_signals),
            "commands": len(self.commands),
            "compounds": len(self.compounds),
            "libraries": len(self.libraries),
            "tolerances": len(self.tolerances),
            "app_parameters": len(self.app_parameters),
            "model_signals": len(self.model_signals),
            "configurations": len(self.configurations),
            "global_variables": len(self.global_variables),
        }

    def merge(self, other: KnowledgeBase) -> None:
        """Fold another knowledge base into this one (multiple input files)."""
        for field in type(self).model_fields:
            if field == "notes":
                for key, value in other.notes.items():
                    self.notes.setdefault(key, []).extend(value)
                continue
            current: list[Any] = getattr(self, field)
            current.extend(getattr(other, field))
