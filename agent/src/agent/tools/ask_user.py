"""ask_user tool — request human confirmation or input.

This is the safety valve: high-risk tools route through here, and the
LLM itself can call it to ask the user a question.  The actual WS
round-trip (emit tool.request_confirm, wait for tool.confirm) is
handled by the TurnLoop / WS layer; this tool just provides the
schema and a stub execute that the orchestrator replaces with the
real approval flow.
"""

from __future__ import annotations

from typing import Any

from agent.tools.base import Tool


class AskUserTool(Tool):
    name = "ask_user"
    description = (
        "Ask the user a question or request confirmation before proceeding. "
        "Use this when you need human input to continue."
    )
    risk = "low"
    requires_confirmation = False  # This IS the confirmation mechanism

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["question"],
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to ask the user",
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        # In practice, the orchestrator intercepts ask_user calls and
        # routes them through the WS confirm flow. This fallback exists
        # so the tool can be registered and tested in isolation.
        return {"answer": "(no answer — ask_user requires WS confirm flow)"}
