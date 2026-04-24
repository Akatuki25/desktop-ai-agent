"""Lock-guarded LLM backend wrapper.

llama-server handles one request at a time by default. If the scheduler's
proactive driver fires while a chat turn is streaming, the second request
gets a 500. This wrapper serializes all chat_stream calls through a
shared asyncio.Lock so the proactive driver simply waits until the
current turn finishes.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from agent.llm.backend import LLMBackend, LLMChunk, Message


class LockedLLMBackend:
    """Wraps any LLMBackend with an asyncio.Lock for serialized access."""

    def __init__(self, inner: LLMBackend) -> None:
        self._inner = inner
        self._lock = asyncio.Lock()

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        tools: list[dict[str, object]] | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[LLMChunk]:
        async with self._lock:
            async for chunk in self._inner.chat_stream(
                messages, tools=tools, thinking=thinking
            ):
                yield chunk
