"""Selecting the requirements a SYS5 run must cover."""

from __future__ import annotations

import logging

from ..models import Requirement, RequirementRow
from ..projects import ProjectProfile
from ..utils.text import contains_any, normalize

logger = logging.getLogger(__name__)


def select_requirements(
    rows: list[RequirementRow], keywords: list[str], profile: ProjectProfile
) -> tuple[list[Requirement], str]:
    """Pick the rows that describe SYS5-testable requirements.

    The marker keyword can sit in any column — Verification Stage on one sheet, Remarks
    or Category on another — so every cell of every row is scanned rather than one
    designated column.

    Returns the selected requirements and a description of how they were chosen.
    """
    selected: list[Requirement] = []

    for row in rows:
        if row.is_context_row():
            continue
        matched = contains_any(row.searchable_text(), keywords)
        if matched:
            selected.append(Requirement.from_row(row, selected_by=f"keyword:{matched}"))

    if selected:
        return selected, f"keyword match ({', '.join(keywords)})"

    # Nothing matched. Rather than return an empty run, fall back to the category
    # column — but say so loudly, because it usually means the keyword list needs
    # updating for this project's spreadsheet conventions.
    fallback_categories = {normalize(c) for c in profile.fallback_categories}
    for row in rows:
        if row.is_context_row():
            continue
        if normalize(row.category) in fallback_categories:
            selected.append(Requirement.from_row(row, selected_by="fallback:category"))

    if selected:
        logger.warning(
            "[sys5] no row matched the SYS5 keywords %s; fell back to Category in %s "
            "and selected %d requirement(s). Check `req_keywords` for this project.",
            keywords,
            list(profile.fallback_categories),
            len(selected),
        )
        return selected, f"fallback: Category in {list(profile.fallback_categories)}"

    logger.error(
        "[sys5] no requirements selected: neither the keywords %s nor the categories %s "
        "matched any of the %d rows",
        keywords,
        list(profile.fallback_categories),
        len(rows),
    )
    return [], "none matched"
