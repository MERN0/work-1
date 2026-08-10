"""Parsers for the configuration workbook.

Covers *Tolerances*, *Configurations*, *Model_Input_Mapping* and *Global_Variables* —
the sheets that define what values a ``Set`` may legally carry and how an expected value
must be written.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import ConfigurationEnum, GlobalVariable, ModelSignal, Provenance, Tolerance
from ...utils.text import clean, parse_enum_map, parse_tolerance_pair
from ..workbook import load_sheet

logger = logging.getLogger(__name__)

TOLERANCE_HEADERS = [
    "Sl No",
    "Tolerance Configuration",
    "Description",
    "Example",
    "Unit",
    "Value",
    "Tolerance Unit",
    "Remarks",
]
CONFIGURATION_HEADERS = ["Sl No", "Signal Name", "Signal Description", "Configuration", "Remarks"]
MODEL_INPUT_HEADERS = [
    "Sl.No.",
    "Signal",
    "Test Case Input",
    "Model Input",
    "Model Output to ECU",
    "Remark",
]
GLOBAL_HEADERS = ["Sl No", "Variable", "Value", "Description"]


def parse_tolerances(path: Path, sheet: str) -> list[Tolerance]:
    """Read the ``Config_Tol_*`` definitions.

    ``Value`` holds the positive and negative tolerances as a pair (``0.5,1.5``); a
    single value applies to both sides.
    """
    table = load_sheet(path, sheet, TOLERANCE_HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    tolerances: list[Tolerance] = []
    for row in table.rows:
        name = row.get("Tolerance Configuration", "Tolerance", "Configuration")
        if not name:
            continue
        positive, negative = parse_tolerance_pair(row.get("Value"))
        tolerances.append(
            Tolerance(
                name=name,
                description=row.get("Description"),
                unit=row.get("Unit"),
                value=row.get("Value"),
                tolerance_unit=row.get("Tolerance Unit", "ToleranceUnit"),
                positive=positive,
                negative=negative,
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d tolerances", path.name, sheet, len(tolerances))
    return tolerances


def parse_configurations(path: Path, sheet: str) -> list[ConfigurationEnum]:
    """Read enumerated signal values such as ``0x00:H, 0x01:P, 0x02:S``."""
    table = load_sheet(path, sheet, CONFIGURATION_HEADERS)
    if not table:
        return []

    enums: list[ConfigurationEnum] = []
    for row in table.rows:
        signal = row.get("Signal Name", "SignalName", "Signal")
        raw = row.get("Configuration", "Configurations")
        if not signal or not raw:
            continue
        enums.append(
            ConfigurationEnum(
                signal_name=signal,
                description=row.get("Signal Description", "Description"),
                values=parse_enum_map(raw),
                raw=raw,
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d configuration enums", path.name, sheet, len(enums))
    return enums


def parse_model_input_mapping(path: Path, sheet: str) -> list[ModelSignal]:
    """Read the ``MDL_*`` signals and the values a test case may set them to.

    The ``Signal`` column is merged across the rows that list its accepted inputs; the
    workbook reader expands those merges, so grouping by signal name recovers the full
    set of legal values. This is the authority the semantic validator consults before
    accepting a ``Set`` parameter.
    """
    table = load_sheet(path, sheet, MODEL_INPUT_HEADERS)
    if not table:
        return []

    grouped: dict[str, ModelSignal] = {}
    for row in table.rows:
        signal = row.get("Signal", "Signal Name")
        if not signal:
            continue

        record = grouped.get(signal)
        if record is None:
            record = ModelSignal(
                name=signal,
                description=row.get("Remark", "Remarks"),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
            grouped[signal] = record

        test_input = clean(row.get("Test Case Input", "TestCaseInput"))
        model_input = clean(row.get("Model Input", "ModelInput"))
        if test_input and test_input != "-" and test_input not in record.allowed_inputs:
            record.allowed_inputs.append(test_input)
        if model_input and model_input not in record.model_inputs:
            record.model_inputs.append(model_input)

    signals = list(grouped.values())
    logger.info("[sys5] %s[%s]: %d model signals", path.name, sheet, len(signals))
    return signals


def parse_global_variables(path: Path, sheet: str) -> list[GlobalVariable]:
    """Read the global-variable sheet.

    Its layout is not fixed across projects, so the first column is taken as the name
    and the first other populated column as the value.
    """
    table = load_sheet(path, sheet, GLOBAL_HEADERS)
    if not table or not table.headers:
        return []

    name_header = table.headers[0]
    variables: list[GlobalVariable] = []
    for row in table.rows:
        name = row.get("Variable", "Name", "Global Variable") or clean(
            row.values.get(name_header, "")
        )
        if not name:
            continue
        value = row.get("Value", "Default", "Setting")
        if not value:
            others = [v for k, v in row.non_empty().items() if k != name_header]
            value = others[0] if others else ""
        variables.append(
            GlobalVariable(
                name=name,
                value=value,
                description=row.get("Description", "Remarks"),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d global variables", path.name, sheet, len(variables))
    return variables
