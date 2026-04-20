"""Tool ABC — every tool the LLM can call inherits from this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal

RiskLevel = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str
    ok: bool
    data: Any = None
    error: str | None = None


class Tool(ABC):
    name: str
    description: str
    risk: RiskLevel = "low"
    requires_confirmation: bool = False

    @abstractmethod
    def parameters_schema(self) -> dict[str, Any]:
        """Return JSON Schema for the tool's parameters."""
        ...

    @abstractmethod
    async def execute(self, args: dict[str, Any]) -> Any:
        """Run the tool and return the result payload."""
        ...

    def openai_schema(self) -> dict[str, Any]:
        """Return the OpenAI-compatible function tool definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema(),
            },
        }
