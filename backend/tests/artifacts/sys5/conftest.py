"""Shared fixtures for the SYS5 tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.artifacts.sys5.indexing import VocabularyIndex
from app.core.artifacts.sys5.ingest import build_inventory, load_knowledge_base
from app.core.artifacts.sys5.ingest.sources import requirements as requirements_source
from app.core.artifacts.sys5.models import Requirement
from app.core.artifacts.sys5.projects import TMHC_PROFILE
from app.core.artifacts.sys5.utils.io import discover_workbooks

from .fixtures import build_all

REQ_FILENAME = "TE_TMHC_HILS Development & Testing_System Requirements.xlsx"


@pytest.fixture(scope="session")
def input_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A directory of synthetic TMHC-shaped input workbooks."""
    directory = tmp_path_factory.mktemp("sys5_inputs")
    build_all(directory)
    return directory


@pytest.fixture(scope="session")
def inventory(input_dir: Path):
    return build_inventory(discover_workbooks(input_dir), REQ_FILENAME)


@pytest.fixture(scope="session")
def knowledge(inventory):
    return load_knowledge_base(inventory)


@pytest.fixture(scope="session")
def index(knowledge) -> VocabularyIndex:
    return VocabularyIndex.from_knowledge(knowledge)


@pytest.fixture(scope="session")
def parsed_sheet(inventory):
    """``(identity, feature_context, rows)`` for feature sheet 005."""
    sheet = inventory.requirement_sheets()[0]
    return requirements_source.parse_requirement_sheet(sheet.path, sheet.sheet)


@pytest.fixture(scope="session")
def requirement(parsed_sheet) -> Requirement:
    """The maximum-speed-limitation requirement."""
    _, _, rows = parsed_sheet
    row = next(r for r in rows if r.requirement_id.endswith("005011"))
    return Requirement.from_row(row, "keyword:system qualification")


@pytest.fixture
def profile():
    return TMHC_PROFILE
