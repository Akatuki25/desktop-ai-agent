"""ToolRegistry — register, look up, and list tools."""

from __future__ import annotations

from typing import Any

from agent.tools.base import Tool


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def all(self) -> list[Tool]:
        return list(self._tools.values())

    def openai_schemas(self) -> list[dict[str, Any]]:
        """All registered tools as OpenAI-compatible tool definitions."""
        return [t.openai_schema() for t in self._tools.values()]
