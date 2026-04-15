"""SQLite-backed session / memory / FTS5 layer.

Everything session-based per docs/spec-detailed.md §3.5 — no knowledge
graph, no vector store. Hot context comes from core_memory +
behavior_config + the N most recent session summaries; cold lookup
uses FTS5 over messages and session summaries via memory.search.
"""

from agent.memory.behavior import BehaviorConfig
from agent.memory.core import CoreMemory
from agent.memory.db import Database
from agent.memory.search import MemorySearch, SearchHit
from agent.memory.sessions import (
    Message,
    Session,
    SessionKind,
    SessionRepository,
)

__all__ = [
    "BehaviorConfig",
    "CoreMemory",
    "Database",
    "MemorySearch",
    "Message",
    "SearchHit",
    "Session",
    "SessionKind",
    "SessionRepository",
]
