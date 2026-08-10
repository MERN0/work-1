"""Construction of the chat model.

``ChatOpenAI`` is the only supported client, pointed at the on-prem OpenAI-compatible
endpoint that serves gpt-oss-120b. Nothing else in the package imports langchain
directly, so swapping the transport would be a change to this module alone.
"""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from ..settings import LLMSettings

logger = logging.getLogger(__name__)


class LLMNotConfiguredError(RuntimeError):
    """Raised when a live call is attempted without connection settings."""


def build_chat_model(settings: LLMSettings) -> BaseChatModel:
    """Build the ``ChatOpenAI`` client for this run.

    Fails immediately when the endpoint is not configured: a run that would produce
    nothing should cost nothing, and the alternative is discovering the problem after
    ingestion and tracing have already been paid for.
    """
    if not settings.is_configured():
        missing = [
            name
            for name, value in (("base_url", settings.base_url), ("api_key", settings.api_key))
            if not value
        ]
        raise LLMNotConfiguredError(
            f"LLM {' and '.join(missing)} not set. Provide SYS5_LLM_BASE_URL / "
            "SYS5_LLM_API_KEY (or OPENAI_BASE_URL / OPENAI_API_KEY), or the "
            "llm_base_url / llm_api_key config keys."
        )

    logger.info(
        "[sys5] chat model %s at %s (temp=%s, max_tokens=%d, timeout=%ds)",
        settings.model,
        settings.base_url,
        settings.temperature,
        settings.max_tokens,
        settings.timeout,
    )

    return ChatOpenAI(
        model=settings.model,
        base_url=settings.base_url,
        api_key=settings.api_key,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        timeout=settings.timeout,
        # Transport-level retries. Node-level retries (LangGraph RetryPolicy) sit above
        # this and cover the whole step, including a malformed-response reparse.
        max_retries=settings.max_retries,
    )
