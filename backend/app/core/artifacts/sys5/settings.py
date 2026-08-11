"""Runtime settings: environment variables merged with the caller's config dict.

Precedence, highest first:

1. keys in the config dict passed to :func:`generate`
2. ``SYS5_*`` environment variables
3. ``OPENAI_*`` environment variables (LLM connection only)
4. the defaults declared here

Everything is resolved and validated *before* the graph runs, so a typo in a template
name or a missing base URL fails in milliseconds rather than after an expensive
generation pass.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

StructuredMethod = Literal["auto", "json_schema", "json_mode", "function_calling"]

#: Keyword list used to select SYS5-relevant requirement rows.
DEFAULT_REQ_KEYWORDS = [
    "sys5 test",
    "sys test",
    "system qualification",
    "system test",
    "sqt",
]


def _env(*names: str, default: str | None = None) -> str | None:
    """First non-empty value among ``names``, else ``default``."""
    for name in names:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_int(value: Any, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        return int(str(value).strip())
    except ValueError:
        return default


def _as_float(value: Any, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        return float(str(value).strip())
    except ValueError:
        return default


class LLMSettings(BaseModel):
    """Connection and budget settings for the on-prem OpenAI-compatible endpoint."""

    model_config = ConfigDict(extra="forbid")

    base_url: str = ""
    api_key: str = ""
    model: str = "llm-1-gpt-oss-120b"
    temperature: float = 0.0
    max_tokens: int = 8192
    context_limit: int = 100_000
    context_reserve: int = 8_000
    timeout: int = 180
    max_retries: int = 3
    max_concurrency: int = 3
    structured_method: StructuredMethod = "auto"

    @property
    def prompt_budget(self) -> int:
        """Tokens available for the prompt, after reserving room for the completion."""
        return max(1_000, self.context_limit - self.context_reserve)

    def is_configured(self) -> bool:
        """True when a live call could be attempted."""
        return bool(self.base_url and self.api_key)


class Sys5Settings(BaseModel):
    """Fully-resolved settings for one :func:`generate` invocation."""

    model_config = ConfigDict(extra="forbid")

    # --- identity -----------------------------------------------------------
    project_name: str = "default_project"
    username: str = "default_user"
    version: str = "v1.0"
    domain: str = ""
    artifact: str = "SYS5"
    language: str = ""

    # --- paths --------------------------------------------------------------
    input_dir: Path = Field(default_factory=Path)
    output_dir: Path = Field(default_factory=Path)
    work_dir: Path = Field(default_factory=Path)
    uploaded_files: list[str] = Field(default_factory=list)
    req_filename: str = ""
    req_sheet_name: str = ""

    # --- selection / tracing ------------------------------------------------
    req_keywords: list[str] = Field(default_factory=lambda: list(DEFAULT_REQ_KEYWORDS))
    fuzzy_threshold: int = 85

    #: Full list of applicable variants (e.g. A1, A2, B, C1...). Empty means "use the
    #: project profile's list" — see `generate()` in sys5.py.
    available_variants: list[str] = Field(default_factory=list)

    # --- output -------------------------------------------------------------
    output_template: str = "tmhc_v1"
    output_format: str = "excel"
    project_profile: str = "tmhc"

    # --- pipeline -----------------------------------------------------------
    max_validation_attempts: int = 2
    max_correction_attempts: int = 1
    keep_intermediates: bool = True
    checkpoint_db: str = ""
    log_level: str = "INFO"

    # --- llm ----------------------------------------------------------------
    llm: LLMSettings = Field(default_factory=LLMSettings)

    # --- misc ---------------------------------------------------------------
    agent_chain: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("req_keywords")
    @classmethod
    def _non_empty_keywords(cls, value: list[str]) -> list[str]:
        cleaned = [k.strip() for k in value if k and k.strip()]
        return cleaned or list(DEFAULT_REQ_KEYWORDS)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> Sys5Settings:
        """Build settings from the caller's config dict plus the environment."""
        get = config.get

        output_dir = Path(get("output_folder_path") or get("output_dir") or ".").expanduser()
        input_dir = Path(get("input_folder_path") or ".").expanduser()

        work_dir_raw = get("work_dir") or _env("SYS5_WORK_DIR") or ""
        work_dir = Path(work_dir_raw).expanduser() if work_dir_raw else Path(__file__).parent / "_work"

        keywords_raw = get("req_keywords") or _env("SYS5_REQ_KEYWORDS") or ""
        if isinstance(keywords_raw, str):
            keywords = [k for k in (part.strip() for part in keywords_raw.split(",")) if k]
        else:
            keywords = list(keywords_raw)

        variants_raw = get("available_variants") or _env("SYS5_AVAILABLE_VARIANTS") or ""
        if isinstance(variants_raw, str):
            variants = [v for v in (part.strip() for part in variants_raw.split(",")) if v]
        else:
            variants = list(variants_raw)

        llm = LLMSettings(
            base_url=str(
                get("llm_base_url") or _env("SYS5_LLM_BASE_URL", "OPENAI_BASE_URL") or ""
            ),
            api_key=str(get("llm_api_key") or _env("SYS5_LLM_API_KEY", "OPENAI_API_KEY") or ""),
            model=str(
                get("llm_model") or get("model") or _env("SYS5_LLM_MODEL") or "llm-1-gpt-oss-120b"
            ),
            temperature=_as_float(
                get("llm_temperature", _env("SYS5_LLM_TEMPERATURE")), 0.0
            ),
            max_tokens=_as_int(get("llm_max_tokens", _env("SYS5_LLM_MAX_TOKENS")), 8192),
            context_limit=_as_int(
                get("llm_context_limit", _env("SYS5_LLM_CONTEXT_LIMIT")), 100_000
            ),
            context_reserve=_as_int(
                get("llm_context_reserve", _env("SYS5_LLM_CONTEXT_RESERVE")), 8_000
            ),
            timeout=_as_int(get("llm_timeout", _env("SYS5_LLM_TIMEOUT")), 180),
            max_retries=_as_int(get("llm_max_retries", _env("SYS5_LLM_MAX_RETRIES")), 3),
            max_concurrency=_as_int(
                get("llm_max_concurrency", _env("SYS5_LLM_MAX_CONCURRENCY")), 3
            ),
            structured_method=str(
                get("llm_structured_method")
                or _env("SYS5_LLM_STRUCTURED_METHOD")
                or "auto"
            ).lower(),  # type: ignore[arg-type]
        )

        return cls(
            project_name=str(get("project_name") or "default_project"),
            username=str(get("username") or "default_user"),
            version=str(get("version") or "v1.0"),
            domain=str(get("domain") or ""),
            artifact=str(get("artifact") or "SYS5"),
            language=str(get("language") or ""),
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
            uploaded_files=[str(f) for f in (get("uploaded_files") or [])],
            req_filename=str(get("req_filename") or ""),
            req_sheet_name=str(get("req_sheet_name") or "").strip(),
            req_keywords=keywords or list(DEFAULT_REQ_KEYWORDS),
            fuzzy_threshold=_as_int(get("fuzzy_threshold", _env("SYS5_FUZZY_THRESHOLD")), 85),
            available_variants=variants,
            output_template=str(
                get("output_template") or _env("SYS5_OUTPUT_TEMPLATE") or ""
            ).strip(),
            output_format=str(
                get("output_format") or _env("SYS5_OUTPUT_FORMAT") or "excel"
            ).strip().lower(),
            project_profile=str(
                get("project_profile") or _env("SYS5_PROJECT_PROFILE") or ""
            ).strip(),
            max_validation_attempts=_as_int(
                get("max_validation_attempts", _env("SYS5_MAX_VALIDATION_ATTEMPTS")), 2
            ),
            max_correction_attempts=_as_int(
                get("max_correction_attempts", _env("SYS5_MAX_CORRECTION_ATTEMPTS")), 1
            ),
            keep_intermediates=_as_bool(
                get("keep_intermediates", _env("SYS5_KEEP_INTERMEDIATES")), True
            ),
            checkpoint_db=str(get("checkpoint_db") or _env("SYS5_CHECKPOINT_DB") or ""),
            log_level=str(get("log_level") or _env("SYS5_LOG_LEVEL") or "INFO").upper(),
            llm=llm,
            agent_chain=list(get("agent_chain") or []),
        )
