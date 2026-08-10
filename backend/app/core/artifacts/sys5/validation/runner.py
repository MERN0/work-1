"""Runs every validator over a test case and reports the combined result."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from ..indexing import VocabularyIndex
from ..models import TestCase, TestCasePlan, ValidationIssue
from ..projects import ProjectProfile
from ..utils.text import normalize
from .semantics import check_semantics
from .structure import check_structure
from .vocabulary import check_vocabulary

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ValidationResult:
    """The outcome of validating one test case."""

    issues: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def render(self, limit: int = 25) -> str:
        """The issue list as prompt text for a repair round."""
        lines = [issue.render() for issue in self.issues[:limit]]
        if len(self.issues) > limit:
            lines.append(f"... and {len(self.issues) - limit} more")
        return "\n".join(lines)

    def codes(self) -> list[str]:
        return sorted({issue.code for issue in self.issues})


def validate_case(
    case: TestCase,
    index: VocabularyIndex,
    profile: ProjectProfile,
    plan: TestCasePlan | None = None,
) -> ValidationResult:
    """Validate one test case against every rule.

    Order matters: structure first (a case with no steps has nothing else worth
    checking), then grammar and vocabulary, then semantics — which needs the parse the
    vocabulary pass already produced.
    """
    issues: list[ValidationIssue] = list(check_structure(case, profile))

    vocabulary_issues, parsed = check_vocabulary(case, index, profile)
    issues.extend(vocabulary_issues)
    issues.extend(check_semantics(case, parsed, index))

    if plan is not None:
        issues.extend(_check_coverage(case, plan))

    warnings = [i for i in issues if i.code in profile.tolerated_issue_codes]
    errors = [i for i in issues if i.code not in profile.tolerated_issue_codes]

    result = ValidationResult(issues=errors, warnings=warnings)
    if not result.ok:
        logger.debug(
            "[sys5] %s failed validation: %s", case.tc_id or case.aspect, result.codes()
        )
    return result


def _check_coverage(case: TestCase, plan: TestCasePlan) -> list[ValidationIssue]:
    """The generated case must actually exercise what the planner said it would.

    Without this, a model that finds a requirement hard can quietly produce a plausible
    but unrelated test case, and every other check would still pass.
    """
    issues: list[ValidationIssue] = []
    body = normalize(
        " ".join(
            f"{s.text} {s.parameter} {s.expected} {s.remark}" for s in case.steps
        )
    )

    missing = [
        boundary
        for boundary in plan.ranges_or_boundaries
        if boundary and normalize(boundary) not in body
    ]
    if missing and len(missing) == len(plan.ranges_or_boundaries):
        issues.append(
            ValidationIssue(
                code="COVERAGE_GAP",
                message=(
                    "none of the planned values "
                    f"({', '.join(plan.ranges_or_boundaries)}) appear in the steps"
                ),
                suggestion=(
                    "exercise the planned boundary values explicitly in the ACTION phase"
                ),
            )
        )

    return issues


def summarise(results: list[ValidationResult]) -> dict[str, int]:
    """Issue counts by code across a run, for the summary log."""
    counts: dict[str, int] = {}
    for result in results:
        for issue in result.issues:
            counts[issue.code] = counts.get(issue.code, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))
