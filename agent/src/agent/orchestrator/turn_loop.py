"""One-turn text chat loop.

Flow:
1. locate / create the current chat session
2. persist the user message
3. build a prompt from hot context + message history
4. stream from the LLM, yielding SayEvent(delta, is_thinking) per chunk
5. accumulate the assistant's full reply and persist it
6. emit a final SayEnd sentinel

Everything is framework-agnostic — the WS layer subscribes to the
async iterator and forwards each SayEvent as a JSON-RPC notification.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass

from agent.llm.backend import LLMBackend
from agent.memory import BehaviorConfig, CoreMemory, SessionRepository
from agent.orchestrator.prompt import build_messages, build_system_prompt
from agent.orchestrator.session import SessionManager


@dataclass(frozen=True)
class SayEvent:
    kind: str  # "delta" | "end"
    text: str = ""
    is_thinking: bool = False
    message_id: str = ""


class TurnLoop:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        session_manager: SessionManager,
        core_memory: CoreMemory,
        behavior: BehaviorConfig,
        llm: LLMBackend,
        history_window: int = 30,
    ) -> None:
        self._sessions = sessions
        self._session_manager = session_manager
        self._core = core_memory
        self._behavior = behavior
        self._llm = llm
        self._history_window = history_window

    async def run(self, user_text: str) -> AsyncIterator[SayEvent]:
        session = self._session_manager.current_or_new_chat()
        self._sessions.append_message(session.id, "user", user_text)

        system_prompt = build_system_prompt(self._core, self._behavior, self._sessions)
        history = self._sessions.recent_messages(session.id, self._history_window)
        prompt = build_messages(system_prompt, history)

        main_buffer: list[str] = []
        thinking_buffer: list[str] = []

        async for chunk in self._llm.chat_stream(prompt, thinking=False):
            if chunk.done:
                break
            if chunk.is_thinking:
                thinking_buffer.append(chunk.text)
            else:
                main_buffer.append(chunk.text)
            yield SayEvent(
                kind="delta",
                text=chunk.text,
                is_thinking=chunk.is_thinking,
            )

        final_text = "".join(main_buffer).strip()
        if final_text:
            stored = self._sessions.append_message(session.id, "assistant", final_text)
            yield SayEvent(kind="end", message_id=str(stored.id))
        else:
            yield SayEvent(kind="end", message_id="")
