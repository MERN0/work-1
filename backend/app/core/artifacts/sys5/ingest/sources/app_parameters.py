"""Parser for *Master List - App Parameter*."""

from __future__ import annotations

import logging
from pathlib import Path

from ...models import AppParameter, Provenance
from ..workbook import load_sheet
from ._common import feature_columns, marked_features

logger = logging.getLogger(__name__)

HEADERS = [
    "Parameter ID",
    "Parameter Name",
    "Parameter Description(purpose)",
    "Parameter Type",
    "Unit",
    "Parameter Valid Value",
    "Parameter default value",
    "Parameter min Value",
    "Parameter max Value",
    "Resolution",
    "Interdependency with other parameters",
    "Linked System Requirement",
]


def parse(path: Path, sheet: str) -> list[AppParameter]:
    """Read calibration/configuration parameters with their valid ranges.

    The min/max/valid columns are what the semantic validator uses to reject a ``Set``
    value that falls outside what the system accepts.
    """
    table = load_sheet(path, sheet, HEADERS)
    if not table:
        logger.warning("[sys5] %s[%s]: no table found", path.name, sheet)
        return []

    columns = feature_columns(table)
    parameters: list[AppParameter] = []

    for row in table.rows:
        parameter_id = row.get("Parameter ID", "ParameterID")
        name = row.get("Parameter Name", "ParameterName")
        if not (parameter_id or name):
            continue

        parameters.append(
            AppParameter(
                name=name or parameter_id,
                aliases=[a for a in (parameter_id,) if a],
                description=row.get(
                    "Parameter Description(purpose)", "Parameter Description", "Description"
                ),
                parameter_id=parameter_id,
                parameter_type=row.get("Parameter Type", "ParameterType"),
                unit=row.get("Unit"),
                valid_value=row.get("Parameter Valid Value", "Valid Value"),
                default_value=row.get("Parameter default value", "Default Value"),
                min_value=row.get("Parameter min Value", "Min Value"),
                max_value=row.get("Parameter max Value", "Max Value"),
                resolution=row.get("Resolution"),
                linked_requirement=row.get(
                    "Linked System Requirement", "Linked Sys Req", "Linked System Req"
                ),
                features=marked_features(row, columns),
                provenance=Provenance(file=table.file, sheet=table.sheet, row=row.number),
            )
        )

    logger.info("[sys5] %s[%s]: %d app parameters", path.name, sheet, len(parameters))
    return parameters
