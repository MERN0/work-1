"""Pure-Python preprocessing: load workbooks, filter to sys-qualification rows,
drop junk/heading rows, and build the in-memory supporting-doc registry.
No LLM calls anywhere in this module (ARCHITECTURE.md Sec2 / Sec11).
"""

from __future__ import annotations

import re
from pathlib import Path

from config_loader import RunConfig
from logging_setup import get_logger, log_data, stage
from schemas import RequirementRow, SupportingDocItem
from tools.excel_io import header_and_rows, load_workbook_sheets, row_to_text

log = get_logger("preprocessing")


def _is_junk_row(header: list[str], row: list, rules: dict) -> bool:
    non_empty = [c for c in row if c not in (None, "")]
    min_non_empty = rules.get("min_non_empty_cells", 1)
    if len(non_empty) < min_non_empty:
        return True

    max_empty_fraction = rules.get("max_empty_fraction")
    if max_empty_fraction is not None and len(row) > 0:
        empty_fraction = 1 - (len(non_empty) / len(row))
        if empty_fraction > max_empty_fraction:
            return True

    first_cell = str(row[0]).strip() if row and row[0] not in (None, "") else ""
    for pattern in rules.get("heading_patterns", []):
        if re.match(pattern, first_cell, flags=re.IGNORECASE):
            return True

    return False


def _matches_keywords(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)


def filter_requirement_rows(
    workbook_paths: list[Path],
    config: RunConfig,
) -> list[RequirementRow]:
    """Row filter + junk exclusion, per ARCHITECTURE.md Sec2.2/Sec2.3."""
    rules = config.exclusion_rules
    keywords = rules.get("match_keywords", ["sys qualification", "sys5"])
    filter_column = rules.get("filter_column")

    results: list[RequirementRow] = []
    with stage(log, "filter_requirement_rows", workbooks=len(workbook_paths)):
        for path in workbook_paths:
            sheets = load_workbook_sheets(path)
            for sheet_name, rows in sheets.items():
                header, data_rows = header_and_rows(rows)
                kept_in_sheet = 0
                junk_in_sheet = 0
                for i, row in enumerate(data_rows, start=2):  # +1 for header, +1 for 1-index
                    if _is_junk_row(header, row, rules):
                        junk_in_sheet += 1
                        continue

                    if filter_column and filter_column in header:
                        col_idx = header.index(filter_column)
                        cell_text = str(row[col_idx]) if col_idx < len(row) and row[col_idx] is not None else ""
                        matched = _matches_keywords(cell_text, keywords)
                    else:
                        matched = _matches_keywords(row_to_text(row), keywords)

                    if not matched:
                        continue

                    columns = {header[j]: ("" if j >= len(row) or row[j] is None else str(row[j])) for j in range(len(header))}
                    req = RequirementRow(
                        requirement_id=columns.get("Requirement ID") or columns.get("Requirement_ID") or f"{sheet_name}_R{i}",
                        source_file=path.name,
                        source_sheet=sheet_name,
                        row_index=i,
                        columns=columns,
                        raw_text=row_to_text(row),
                    )
                    results.append(req)
                    kept_in_sheet += 1

                log.info(
                    "  %s / '%s': %d data rows -> %d kept, %d junk, %d unmatched",
                    path.name, sheet_name, len(data_rows), kept_in_sheet, junk_in_sheet,
                    len(data_rows) - kept_in_sheet - junk_in_sheet,
                )

        log.info("Total requirement rows kept after filtering: %d", len(results))
        log_data(log, "kept requirement IDs", [r.requirement_id for r in results])

    return results


def build_supporting_doc_registry(workbook_paths: list[Path]) -> list[SupportingDocItem]:
    """No key join to requirements exists -- this just normalizes every
    supporting-doc row into the registry; relevance is inferred later by an
    LLM node (supporting_doc_planner). Optional: returns [] cleanly if no
    supporting docs were supplied."""
    registry: list[SupportingDocItem] = []
    if not workbook_paths:
        log.info("No supporting docs supplied -- registry is empty, pipeline continues normally")
        return registry

    with stage(log, "build_supporting_doc_registry", workbooks=len(workbook_paths)):
        for path in workbook_paths:
            sheets = load_workbook_sheets(path)
            for sheet_name, rows in sheets.items():
                header, data_rows = header_and_rows(rows)
                for i, row in enumerate(data_rows, start=2):
                    if all(c in (None, "") for c in row):
                        continue
                    row_data = {header[j]: ("" if j >= len(row) or row[j] is None else str(row[j])) for j in range(len(header))}
                    registry.append(
                        SupportingDocItem(source_file=path.name, sheet=sheet_name, row_index=i, row_data=row_data)
                    )
                log.info("  %s / '%s': %d rows registered", path.name, sheet_name, len(data_rows))

        log.info("Total supporting-doc registry entries: %d", len(registry))

    return registry
