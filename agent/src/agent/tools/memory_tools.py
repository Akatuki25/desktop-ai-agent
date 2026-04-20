"""Built-in memory tools: memory.search and memory.upsert."""

from __future__ import annotations

from typing import Any

from agent.memory import CoreMemory, MemorySearch
from agent.tools.base import Tool


class MemorySearchTool(Tool):
    name = "memory.search"
    description = (
        "Search past conversations and session summaries by keyword. "
        "Returns matching snippets with session IDs. Use this when you "
        "need to recall something from a previous conversation."
    )
    risk = "low"
    requires_confirmation = False

    def __init__(self, search: MemorySearch) -> None:
        self._search = search

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string", "description": "Search keyword or phrase"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        query = str(args.get("query", ""))
        limit = int(args.get("limit", 10))
        hits = self._search.search(query, limit=limit)
        return [
            {"kind": h.kind, "session_id": h.session_id, "snippet": h.snippet}
            for h in hits
        ]


class MemoryUpsertTool(Tool):
    name = "memory.upsert"
    description = (
        "Update the agent's core memory (user profile, preferences). "
        "This persistently changes what the agent knows about the user."
    )
    risk = "medium"
    requires_confirmation = True

    def __init__(self, core: CoreMemory) -> None:
        self._core = core

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["key", "value"],
            "properties": {
                "key": {"type": "string", "description": "Memory key to set"},
                "value": {"type": "string", "description": "Value to store"},
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        key = str(args.get("key", ""))
        value = str(args.get("value", ""))
        self._core.set(key, value)
        return {"ok": True, "key": key}
