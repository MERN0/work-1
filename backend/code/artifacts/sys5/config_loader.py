"""Loads everything under config/ into plain Python structures. Pure Python,
no LLM calls -- per ARCHITECTURE.md Sec2.5 / Sec11 cost-optimization split.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from logging_setup import get_logger

log = get_logger("config_loader")

DEFAULT_CONFIG_DIR = Path(__file__).parent / "config"


@dataclass
class RunConfig:
    config_dir: Path
    domain: str
    id_format: dict = field(default_factory=dict)
    output_format: dict = field(default_factory=dict)
    step_grammar: dict = field(default_factory=dict)
    exclusion_rules: dict = field(default_factory=dict)
    domain_prompt_text: str = ""
    project_guideline_text: str = ""
    output_format_name: str = "default"
    project: str = "default"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        log.warning("Config file missing, using empty defaults: %s", path)
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_run_config(
    config_dir: Path = DEFAULT_CONFIG_DIR,
    domain: str = "forklift",
    output_format_name: str = "default",
    project: str = "default",
) -> RunConfig:
    log.info("Loading config from %s (domain=%s, format=%s, project=%s)", config_dir, domain, output_format_name, project)

    id_format = _load_yaml(config_dir / "id_format.yaml")
    output_format = _load_yaml(config_dir / "output_formats" / f"{output_format_name}.yaml")
    step_grammar = _load_yaml(config_dir / "step_grammar.yaml")
    exclusion_rules = _load_yaml(config_dir / "exclusion_rules.yaml")

    domain_prompt_path = config_dir / "domain_prompts" / f"{domain}.md"
    if domain_prompt_path.exists():
        domain_prompt_text = domain_prompt_path.read_text(encoding="utf-8")
        log.info("Loaded domain prompt: %s (%d chars)", domain_prompt_path.name, len(domain_prompt_text))
    else:
        domain_prompt_text = ""
        log.warning("No domain prompt file for domain=%s at %s -- generation will run without domain guidance", domain, domain_prompt_path)

    manifest = _load_yaml(config_dir / "project_guidelines" / "manifest.yaml")
    guideline_files = (manifest.get("projects", {}).get(project, {}) or {}).get("files", [])
    guideline_chunks = []
    for rel in guideline_files:
        p = config_dir / "project_guidelines" / rel
        if p.exists():
            guideline_chunks.append(p.read_text(encoding="utf-8"))
        else:
            log.warning("Guideline file listed in manifest but missing on disk: %s", p)
    project_guideline_text = "\n\n".join(guideline_chunks)
    log.info("Loaded %d project guideline file(s) for project=%s", len(guideline_chunks), project)

    return RunConfig(
        config_dir=config_dir,
        domain=domain,
        id_format=id_format,
        output_format=output_format,
        step_grammar=step_grammar,
        exclusion_rules=exclusion_rules,
        domain_prompt_text=domain_prompt_text,
        project_guideline_text=project_guideline_text,
        output_format_name=output_format_name,
        project=project,
    )
