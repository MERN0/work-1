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


def _env(*names: str) -> str:
    """First non-empty environment variable among ``names``, else ``""``."""
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    return ""


def _setting(get, key: str, *env_names: str, default: Any, cast: type = str) -> Any:
    """Resolve one setting: config[key] > env vars (in order) > default.

    A config value of ``0`` or ``False`` is a real, explicit setting and must be kept —
    only ``None``/``""``/a missing key fall through to the environment and then the
    default. ``cast`` may be ``str``, ``int``, ``float`` or ``bool``; a value that fails
    to cast falls back to ``default`` rather than raising.
    """
    raw = get(key)
    if raw in (None, ""):
        raw = _env(*env_names)
    if raw in (None, ""):
        return default
    if cast is bool:
        return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}
    if cast in (int, float):
        try:
            return cast(str(raw).strip())
        except ValueError:
            return default
    return str(raw)


def _setting_list(get, key: str, *env_names: str, default: list[str] | None = None) -> list[str]:
    """Same precedence as :func:`_setting`, but for a comma-separated list."""
    raw = get(key) or _env(*env_names)
    if not raw:
        return list(default or [])
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    return [str(item) for item in raw]


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
    max_cases_per_requirement: int = 5
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
        """Build settings from the caller's config dict plus the environment.

        Every scalar setting follows the same precedence — config value, then env
        vars, then a default — via :func:`_setting`; lists go through
        :func:`_setting_list`. A handful of fields (paths, the model name) need one
        extra step and are resolved inline just below.
        """
        get = config.get

        def setting(key: str, *env: str, default: Any, cast: type = str) -> Any:
            return _setting(get, key, *env, default=default, cast=cast)

        def setting_list(key: str, *env: str, default: list[str] | None = None) -> list[str]:
            return _setting_list(get, key, *env, default=default)

        output_dir = Path(get("output_folder_path") or get("output_dir") or ".").expanduser()
        input_dir = Path(get("input_folder_path") or ".").expanduser()
        work_dir_raw = setting("work_dir", "SYS5_WORK_DIR", default="")
        work_dir = Path(work_dir_raw).expanduser() if work_dir_raw else Path(__file__).parent / "_work"
        model = get("llm_model") or get("model") or _env("SYS5_LLM_MODEL") or "llm-1-gpt-oss-120b"

        llm = LLMSettings(
            base_url=setting("llm_base_url", "SYS5_LLM_BASE_URL", "OPENAI_BASE_URL", default=""),
            api_key=setting("llm_api_key", "SYS5_LLM_API_KEY", "OPENAI_API_KEY", default=""),
            model=model,
            temperature=setting("llm_temperature", "SYS5_LLM_TEMPERATURE", default=0.0, cast=float),
            max_tokens=setting("llm_max_tokens", "SYS5_LLM_MAX_TOKENS", default=8192, cast=int),
            context_limit=setting("llm_context_limit", "SYS5_LLM_CONTEXT_LIMIT", default=100_000, cast=int),
            context_reserve=setting("llm_context_reserve", "SYS5_LLM_CONTEXT_RESERVE", default=8_000, cast=int),
            timeout=setting("llm_timeout", "SYS5_LLM_TIMEOUT", default=180, cast=int),
            max_retries=setting("llm_max_retries", "SYS5_LLM_MAX_RETRIES", default=3, cast=int),
            max_concurrency=setting("llm_max_concurrency", "SYS5_LLM_MAX_CONCURRENCY", default=3, cast=int),
            structured_method=setting(
                "llm_structured_method", "SYS5_LLM_STRUCTURED_METHOD", default="auto"
            ).lower(),
        )

        return cls(
            project_name=setting("project_name", default="default_project"),
            username=setting("username", default="default_user"),
            version=setting("version", default="v1.0"),
            domain=setting("domain", default=""),
            artifact=setting("artifact", default="SYS5"),
            language=setting("language", default=""),
            input_dir=input_dir,
            output_dir=output_dir,
            work_dir=work_dir,
            uploaded_files=[str(f) for f in (get("uploaded_files") or [])],
            req_filename=setting("req_filename", default=""),
            req_sheet_name=setting("req_sheet_name", default="").strip(),
            req_keywords=setting_list("req_keywords", "SYS5_REQ_KEYWORDS", default=DEFAULT_REQ_KEYWORDS),
            fuzzy_threshold=setting("fuzzy_threshold", "SYS5_FUZZY_THRESHOLD", default=85, cast=int),
            available_variants=setting_list("available_variants", "SYS5_AVAILABLE_VARIANTS"),
            output_template=setting("output_template", "SYS5_OUTPUT_TEMPLATE", default="").strip(),
            output_format=setting("output_format", "SYS5_OUTPUT_FORMAT", default="excel").strip().lower(),
            project_profile=setting("project_profile", "SYS5_PROJECT_PROFILE", default="").strip(),
            max_cases_per_requirement=setting(
                "max_cases_per_requirement", "SYS5_MAX_CASES_PER_REQUIREMENT", default=5, cast=int
            ),
            max_validation_attempts=setting(
                "max_validation_attempts", "SYS5_MAX_VALIDATION_ATTEMPTS", default=2, cast=int
            ),
            max_correction_attempts=setting(
                "max_correction_attempts", "SYS5_MAX_CORRECTION_ATTEMPTS", default=1, cast=int
            ),
            keep_intermediates=setting(
                "keep_intermediates", "SYS5_KEEP_INTERMEDIATES", default=True, cast=bool
            ),
            checkpoint_db=setting("checkpoint_db", "SYS5_CHECKPOINT_DB", default=""),
            log_level=setting("log_level", "SYS5_LOG_LEVEL", default="INFO").upper(),
            llm=llm,
            agent_chain=list(get("agent_chain") or []),
        )
