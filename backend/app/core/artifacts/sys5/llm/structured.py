"""Getting reliable JSON out of a self-hosted model.

``with_structured_output`` defaults to ``method="json_schema"``, which a hosted OpenAI
model implements natively. A vLLM/llama.cpp deployment of gpt-oss may implement it,
may support only ``json_object``, or may support neither. Rather than requiring the
operator to know which, this module walks a capability ladder on first use and then
sticks with whatever rung worked:

    json_schema -> json_mode -> function_calling -> plain text + tolerant parse

The bottom rung always works, because it asks for JSON in the prompt and extracts it
from the reply. Combined with the deterministic validators downstream, a model that
returns slightly malformed JSON costs a reparse, not a failed run.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TypeVar

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

SchemaT = TypeVar("SchemaT", bound=BaseModel)

#: The ladder, strongest first.
LADDER = ("json_schema", "json_mode", "function_calling", "text")

#: Fenced code blocks the model may wrap its JSON in.
_FENCE_RE = re.compile(r"```(?:json)?\s*(?P<body>.*?)```", re.DOTALL)


class StructuredOutputError(RuntimeError):
    """Raised when no rung of the ladder produced a valid object."""


def _extract_json(text: str) -> str:
    """Pull the JSON object out of a model reply that may have prose around it."""
    if match := _FENCE_RE.search(text):
        return match.group("body").strip()

    start = text.find("{")
    if start < 0:
        return text.strip()

    # Walk to the matching brace so trailing commentary is discarded.
    depth, in_string, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:].strip()


def _message_text(message: object) -> str:
    """The plain text of a chat response.

    ``BaseMessage.text`` is a property in langchain-core 1.x; older releases exposed it
    as a method. Reading it as an attribute and falling back to ``content`` covers both
    without triggering the deprecation warning.
    """
    text = getattr(message, "text", None)
    if isinstance(text, str):
        return text
    content = getattr(message, "content", message)
    return content if isinstance(content, str) else str(content)


def parse_payload(schema: type[SchemaT], payload: object) -> SchemaT:
    """Validate a model reply into ``schema``, accepting str/dict/model forms."""
    if isinstance(payload, schema):
        return payload
    if isinstance(payload, BaseModel):
        return schema.model_validate(payload.model_dump())
    if isinstance(payload, dict):
        return schema.model_validate(payload)

    text = payload if isinstance(payload, str) else str(payload)
    return schema.model_validate(json.loads(_extract_json(text)))


class StructuredCaller:
    """Calls a chat model and returns a validated pydantic object.

    One instance per run: it remembers which rung of the ladder the endpoint supports so
    the cost of discovering it is paid once, not per call.
    """

    def __init__(
        self,
        model: BaseChatModel,
        method: str = "auto",
        reparse_attempts: int = 1,
    ) -> None:
        self.model = model
        self.reparse_attempts = reparse_attempts
        self._ladder = list(LADDER) if method in ("auto", "", None) else [method, "text"]
        self._method: str | None = None if method in ("auto", "", None) else method
        self.calls = 0

    @property
    def method(self) -> str:
        """The rung currently in use (``"auto"`` before the first call)."""
        return self._method or "auto"

    def invoke(
        self, schema: type[SchemaT], system: str, user: str, tag: str = ""
    ) -> SchemaT:
        """Call the model and return a validated ``schema`` instance."""
        messages: list[BaseMessage] = [SystemMessage(system), HumanMessage(user)]
        last_error: Exception | None = None

        for candidate in self._candidates():
            try:
                result = self._invoke_with(schema, messages, candidate)
            except Exception as exc:  # noqa: BLE001 - each rung fails in its own way
                last_error = exc
                logger.info(
                    "[sys5] structured call %s failed via method=%r (%s); trying the next one",
                    tag or schema.__name__,
                    candidate,
                    type(exc).__name__,
                )
                continue

            if self._method != candidate:
                logger.info("[sys5] structured output settled on method=%r", candidate)
                self._method = candidate
            self.calls += 1
            return result

        raise StructuredOutputError(
            f"could not obtain valid JSON for {tag or schema.__name__}: {last_error}"
        ) from last_error

    def _candidates(self) -> list[str]:
        """Methods to try, in order.

        Once a rung has worked it is tried first, but the weaker rungs stay available
        behind it: a transient failure on the established method should degrade the
        call, not abandon the test case.
        """
        if self._method is None:
            return list(self._ladder)
        if self._method not in self._ladder:
            return [self._method, "text"]
        return self._ladder[self._ladder.index(self._method) :]

    # ------------------------------------------------------------------ rungs
    def _invoke_with(
        self, schema: type[SchemaT], messages: list[BaseMessage], method: str
    ) -> SchemaT:
        if method == "text":
            return self._invoke_text(schema, messages)

        runnable = self.model.with_structured_output(schema, method=method)
        return parse_payload(schema, runnable.invoke(messages))

    def _invoke_text(self, schema: type[SchemaT], messages: list[BaseMessage]) -> SchemaT:
        """Bottom rung: ask for JSON in the prompt and parse it out of the reply."""
        instruction = (
            "Reply with a single JSON object and nothing else — no prose, no markdown "
            "fences. It must conform to this JSON schema:\n"
            f"{json.dumps(schema.model_json_schema(), indent=2)}"
        )
        attempt_messages = [*messages, SystemMessage(instruction)]

        last_error: Exception | None = None
        for attempt in range(self.reparse_attempts + 1):
            response = self.model.invoke(attempt_messages)
            text = _message_text(response)
            try:
                return parse_payload(schema, text)
            except (ValidationError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt >= self.reparse_attempts:
                    break
                logger.info("[sys5] reply was not valid JSON (%s); asking for a correction", exc)
                attempt_messages = [
                    *messages,
                    SystemMessage(instruction),
                    HumanMessage(
                        "Your previous reply could not be parsed:\n"
                        f"{str(exc)[:500]}\n\nReturn only the corrected JSON object."
                    ),
                ]

        raise StructuredOutputError(f"model did not return parseable JSON: {last_error}")
