"""Shared LLM instantiation, reused across every LLM node.

ARCHITECTURE.md Sec8 Q10: the internal endpoint URL, model name and API-key
source haven't been provided yet, so this reads them from environment
variables and falls back to a deterministic MockChatModel when they're
missing (or SYS5_MOCK_LLM=1 is set), so the pipeline can still be built and
tested end-to-end. Per the master prompt's explicit warning, the real client
is always passed to LangChain as an object instance, never a provider string.
"""

from __future__ import annotations

import os

from logging_setup import get_logger

log = get_logger("llm")


class MockChatModel:
    """Stand-in used when no real internal endpoint is configured. Subagents
    check `is_mock(llm)` and take a pure-Python deterministic path instead of
    calling `.invoke()` on this -- this class exists mainly so callers have a
    consistent object to hold and log about, and so future real structured-
    output calls have an obvious thing to swap in for."""

    def __init__(self, reason: str):
        self.reason = reason

    def __repr__(self) -> str:
        return f"MockChatModel({self.reason!r})"


def get_llm():
    """Returns a ChatOpenAI instance (object, not a provider string) if
    SYS5_OPENAI_API_BASE/SYS5_OPENAI_API_KEY/SYS5_MODEL_NAME are all set and
    SYS5_MOCK_LLM isn't forced on; otherwise a MockChatModel, loudly logged."""
    if os.environ.get("SYS5_MOCK_LLM") == "1":
        log.warning("SYS5_MOCK_LLM=1 set explicitly -- using MockChatModel, no real LLM calls will be made")
        return MockChatModel("SYS5_MOCK_LLM=1")

    api_base = os.environ.get("SYS5_OPENAI_API_BASE")
    api_key = os.environ.get("SYS5_OPENAI_API_KEY")
    model_name = os.environ.get("SYS5_MODEL_NAME")

    if not (api_base and api_key and model_name):
        missing = [
            name for name, val in [
                ("SYS5_OPENAI_API_BASE", api_base),
                ("SYS5_OPENAI_API_KEY", api_key),
                ("SYS5_MODEL_NAME", model_name),
            ] if not val
        ]
        log.warning(
            "Missing env var(s) %s -- falling back to MockChatModel (see ARCHITECTURE.md Sec8 Q10). "
            "Set all three to use a real internal LLM endpoint.",
            missing,
        )
        return MockChatModel(f"missing env vars: {missing}")

    from langchain_openai import ChatOpenAI

    log.info("Instantiating ChatOpenAI(model=%s, openai_api_base=%s) as an object instance", model_name, api_base)
    return ChatOpenAI(
        model=model_name,
        openai_api_key=api_key,
        openai_api_base=api_base,
    )


def is_mock(llm) -> bool:
    return isinstance(llm, MockChatModel)
