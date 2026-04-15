"""Session lifecycle + turn loop.

Phase 0 scope: text-only chat, no tool calls. The orchestrator is the
only place that knows about both the memory layer and the LLM backend;
interface/server.py just forwards events between the orchestrator and
the WebSocket.
"""

from agent.orchestrator.prompt import build_messages
from agent.orchestrator.session import SessionManager
from agent.orchestrator.turn_loop import SayEvent, TurnLoop

__all__ = [
    "SayEvent",
    "SessionManager",
    "TurnLoop",
    "build_messages",
]
