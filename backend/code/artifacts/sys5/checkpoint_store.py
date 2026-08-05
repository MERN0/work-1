"""Read/write the JSON run-state checkpoint (state/run_<id>.json). This is the
primary resumability mechanism (ARCHITECTURE.md Sec5): every node reads it to
skip clusters already past its stage, and writes it back after finishing its
work on a cluster, so a killed/restarted process picks up where it left off.
"""

from __future__ import annotations

import json
from pathlib import Path

from logging_setup import get_logger
from schemas import RunState, TestCase

log = get_logger("checkpoint_store")

DEFAULT_STATE_DIR = Path(__file__).parent / "state"


def checkpoint_path(run_id: str, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    return state_dir / f"run_{run_id}.json"


def load_or_create(run_id: str, domain: str, state_dir: Path = DEFAULT_STATE_DIR) -> RunState:
    path = checkpoint_path(run_id, state_dir)
    if path.exists():
        run_state = RunState.model_validate_json(path.read_text(encoding="utf-8"))
        log.info("Resumed existing run state: %s (%s)", path, run_state.summary())
        return run_state

    log.info("No existing checkpoint at %s -- starting fresh run '%s'", path, run_id)
    return RunState(run_id=run_id, domain=domain)


def save(run_state: RunState, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    path = checkpoint_path(run_state.run_id, state_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(run_state.model_dump_json(indent=2), encoding="utf-8")
    log.debug("Checkpoint saved: %s (%s)", path, run_state.summary())
    return path


def _cluster_artifact_dir(run_id: str, state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    return state_dir / f"run_{run_id}_clusters"


def save_cluster_test_cases(run_id: str, cluster_id: str, stage_name: str, test_cases: list[TestCase], state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    """Persist a cluster's generated/verified test cases alongside the JSON
    checkpoint, so a resumed run that skips a cluster already past a stage can
    actually reload its output instead of just skipping blindly."""
    directory = _cluster_artifact_dir(run_id, state_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{cluster_id}_{stage_name}.json"
    path.write_text(json.dumps([tc.model_dump() for tc in test_cases], indent=2, default=str), encoding="utf-8")
    log.debug("Saved %d test case(s) for cluster %s/%s -> %s", len(test_cases), cluster_id, stage_name, path)
    return path


def load_cluster_test_cases(run_id: str, cluster_id: str, stage_name: str, state_dir: Path = DEFAULT_STATE_DIR) -> list[TestCase] | None:
    path = _cluster_artifact_dir(run_id, state_dir) / f"{cluster_id}_{stage_name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    log.debug("Reloaded %d test case(s) for cluster %s/%s from %s", len(data), cluster_id, stage_name, path)
    return [TestCase.model_validate(d) for d in data]
