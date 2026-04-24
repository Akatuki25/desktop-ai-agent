"""Proactive session driver.

When the scheduler fires, this creates a `proactive` session, asks
the LLM to speak the scheduled prompt, and emits the result through
the WS layer so the character's bubble shows the agent's initiative.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Coroutine
from typing import Any

from agent.llm.backend import LLMBackend
from agent.memory import BehaviorConfig, CoreMemory, SessionRepository
from agent.orchestrator.prompt import build_messages, build_system_prompt

# Type for the callback that sends events to all connected WS clients.
BroadcastFn = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class ProactiveDriver:
    def __init__(
        self,
        *,
        repo: SessionRepository,
        core: CoreMemory,
        behavior: BehaviorConfig,
        llm: LLMBackend,
        broadcast: BroadcastFn,
    ) -> None:
        self._repo = repo
        self._core = core
        self._behavior = behavior
        self._llm = llm
        self._broadcast = broadcast

    async def fire(self, prompt: str) -> None:
        """Create a proactive session and stream the LLM's response."""
        try:
            await self._fire_inner(prompt)
        except Exception as e:
            sys.stderr.write(f"[proactive] error during fire: {e}\n")

    async def _fire_inner(self, prompt: str) -> None:
        session = self._repo.create("proactive")
        self._repo.append_message(session.id, "system", prompt)

        system_prompt = build_system_prompt(self._core, self._behavior, self._repo)
        history = self._repo.recent_messages(session.id, 10)
        messages = build_messages(system_prompt, history)

        buf: list[str] = []
        async for chunk in self._llm.chat_stream(messages, thinking=False):
            if chunk.done:
                break
            if not chunk.is_thinking:
                buf.append(chunk.text)
                await self._broadcast(
                    {
                        "jsonrpc": "2.0",
                        "method": "agent.say",
                        "params": {
                            "text": chunk.text,
                            "emotion": "neutral",
                            "is_thinking": False,
                            "delta": True,
                        },
                    }
                )

        final = "".join(buf).strip()
        if final:
            self._repo.append_message(session.id, "assistant", final)

        await self._broadcast(
            {
                "jsonrpc": "2.0",
                "method": "notification.proactive",
                "params": {
                    "text": final,
                    "emotion": "neutral",
                    "urgency": "normal",
                },
            }
        )
        await self._broadcast(
            {
                "jsonrpc": "2.0",
                "method": "agent.say_end",
                "params": {"message_id": "proactive"},
            }
        )

        sys.stderr.write(f"[proactive] fired: {final[:80]!r}\n")
