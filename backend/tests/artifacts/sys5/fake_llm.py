"""A chat model stand-in, so the whole graph can be exercised without a network.

It deliberately refuses ``with_structured_output`` for every native method, which forces
:class:`StructuredCaller` down its capability ladder to the plain-text rung — the same
path a self-hosted endpoint without ``response_format`` support would take. That way the
offline test covers the fallback rather than only the happy path.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


def _plan_payload(case_count: int = 1) -> dict:
    """``case_count`` synthetic planned cases, cycling priority and test type.

    ``case_count`` lets a test ask the fake planner for more cases than the configured
    cap, to exercise ``Sys5Pipeline._cap_plans`` truncation. The first case always
    matches the original single-case payload so existing assertions about its content
    keep working when ``case_count == 1``.
    """
    priorities = ["P3", "P2", "P1"]
    types = ["Normal_System", "Boundary"]
    cases = []
    for i in range(case_count):
        cases.append(
            {
                "aspect": "maximum speed limit at full accelerator"
                if i == 0
                else f"synthetic aspect {i + 1}",
                "description": "Verify the displayed speed is clamped to 10 km/h with the "
                "accelerator fully pressed.",
                "ranges_or_boundaries": ["10 (Config_Tol_Spd)"] if i == 0 else [],
                "priority": "P1" if i == 0 else priorities[i % len(priorities)],
                "variant": "A1",
                "test_type": "Boundary" if i == 0 else types[i % len(types)],
                "precondition_outline": "Power on, forward, park brake released",
                "action_outline": "Press the accelerator and check the displayed speed",
                "postcondition_outline": "Release the pedal and power down",
            }
        )
    return {
        "coverage_rationale": "Covers the stated limit in the forward direction and the "
        "return to zero when the pedal is released.",
        "test_cases": cases,
    }


def _valid_steps() -> dict:
    return {
        "steps": [
            {
                "phase": "PRECONDITION",
                "text": "Test_start",
                "remark": "Begin the qualification test case for the speed limit",
            },
            {
                "phase": "PRECONDITION",
                "text": "Set MDL_SWH_VBKY",
                "parameter": "ON",
                "remark": "Power the truck up so the drive controller is active",
            },
            {
                "phase": "PRECONDITION",
                "text": "Set MDL_SWH_DIR_STATE",
                "parameter": "FWD",
                "remark": "Select forward travel, the direction this limit is stated for",
            },
            {
                "phase": "PRECONDITION",
                "text": "Wait",
                "parameter": "500",
                "parameter_unit": "ms",
                "remark": "Allow the direction selection to be processed by the controller",
            },
            {
                "phase": "ACTION",
                "text": "Set MDL_SEN_Accelerator_Pedal",
                "parameter": "30",
                "remark": "Press the accelerator fully to demand more than the limited speed",
            },
            {
                "phase": "ACTION",
                "text": "Wait",
                "parameter": "2000",
                "parameter_unit": "ms",
                "remark": "Allow the vehicle to reach steady state before measuring speed",
            },
            {
                "phase": "ACTION",
                "text": "Verify CAN_Main_DispSpeed",
                "expected": "10 (Config_Tol_Spd)",
                "expected_unit": "km/h",
                "remark": "Displayed speed must stay clamped at the configured maximum",
            },
            {
                "phase": "POSTCONDITION",
                "text": "Set MDL_SEN_Accelerator_Pedal",
                "parameter": "0",
                "remark": "Release the accelerator so the truck coasts back to a standstill",
            },
            {
                "phase": "POSTCONDITION",
                "text": "Compound Key_Off_A1",
                "remark": "Return the truck to a powered-down, safe resting state",
            },
            {
                "phase": "POSTCONDITION",
                "text": "End_of_test",
                "remark": "Close out the qualification test case execution",
            },
        ]
    }


def _broken_steps() -> dict:
    """A first draft with the failures the validators are meant to catch."""
    return {
        "steps": [
            {
                "phase": "PRECONDITION",
                "text": "Set Nonexistent_Signal",
                "parameter": "ON",
                "remark": "This references a signal that is not in any input sheet",
            },
            {
                "phase": "ACTION",
                "text": "Read CAN_Main_DispSpeed",
                "remark": "Read is not one of the permitted keywords for a test step",
            },
            {
                "phase": "ACTION",
                "text": "Set MDL_SWH_DIR_STATE",
                "parameter": "SIDEWAYS",
                "remark": "Not one of the accepted direction switch inputs at all",
            },
            {
                "phase": "ACTION",
                "text": "Verify CAN_Main_DispSpeed",
                "expected": "10 (Config_Tol_Invented)",
                "remark": "The tolerance name here was invented and does not exist",
            },
        ]
    }


class FakeChatModel(BaseChatModel):
    """Returns canned JSON based on which prompt it was given."""

    #: When true, the first generation call returns invalid steps and the repair call
    #: returns valid ones — exercising the validate/repair loop.
    fail_first_generation: bool = False

    #: How many cases the fake planner returns per requirement.
    plan_case_count: int = 1

    #: Populated as calls arrive, so a test can assert what was asked.
    prompts: list[str] = []
    generation_calls: int = 0

    @property
    def _llm_type(self) -> str:
        return "fake-sys5"

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Refuse every native structured-output method.

        Mirrors an endpoint that does not implement ``response_format``, so the caller
        has to fall back to prompting for JSON and parsing the reply.
        """
        raise NotImplementedError("this endpoint does not support structured output")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Sequence[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        prompt = "\n".join(str(m.content) for m in messages)
        self.prompts.append(prompt)
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=self._respond(prompt)))]
        )

    def _respond(self, prompt: str) -> str:
        if "failed automated validation" in prompt:
            return json.dumps(_valid_steps())

        if "Plan at most" in prompt:
            return json.dumps(_plan_payload(self.plan_case_count))

        if "Write the ordered steps" in prompt:
            self.generation_calls += 1
            if self.fail_first_generation and self.generation_calls == 1:
                return json.dumps(_broken_steps())
            return json.dumps(_valid_steps())

        return "{}"
