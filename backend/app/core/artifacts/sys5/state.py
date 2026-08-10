"""The LangGraph state schema.

Only serialisable, run-scoped data lives in state. The heavy objects — the knowledge
base, the vocabulary index, the chat model — are held by the pipeline and closed over by
the node functions, which keeps checkpoints small and avoids trying to serialise a
network client.
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from .models import (
    FeatureContext,
    FeatureIdentity,
    Requirement,
    RequirementRow,
    RunSummary,
    TestCase,
    TestCasePlan,
)


class GenerationTask(BaseModel):
    """One unit of fan-out work: write the steps for a single planned test case.

    Carries everything the branch needs, because a ``Send`` payload replaces the state
    for that branch rather than merging into it.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: int
    requirement: Requirement
    plan: TestCasePlan
    #: Pre-rendered, already budget-trimmed reference data for this requirement.
    context_text: str = ""
    #: The exhaustive list of legal names for this requirement.
    vocabulary: list[str] = Field(default_factory=list)


class Sys5State(TypedDict, total=False):
    """State for one requirement sheet's run.

    Every key a node reads must be declared here: LangGraph filters both the initial
    input and each ``Send`` payload down to the schema, so an undeclared key silently
    disappears rather than raising.
    """

    # --- resolved inputs ----------------------------------------------------
    sheet: str
    feature_key: str
    identity: FeatureIdentity
    feature_context: FeatureContext
    rows: list[RequirementRow]

    # --- pipeline products --------------------------------------------------
    requirements: list[Requirement]
    selection_reason: str
    tasks: list[GenerationTask]

    #: Fan-out payload. Present only on a ``Send`` branch.
    task: GenerationTask

    #: Accumulated across parallel branches, hence the reducer.
    generated: Annotated[list[TestCase], operator.add]

    # --- outcome ------------------------------------------------------------
    summary: RunSummary
    output_path: str
