"""LLMBackend Protocol + shared types.

The orchestrator never imports a concrete backend; it accepts anything
that satisfies this Protocol. That keeps the llama-server vs test
substitution trivial.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str


@dataclass(frozen=True)
class LLMChunk:
    """One delta from a streaming LLM response.

    `is_thinking=True` marks tokens that belong to the <think>...</think>
    envelope and should be rendered in the bubble's secondary layer.
    `done=True` is the final sentinel with an empty text.
    """

    text: str
    is_thinking: bool = False
    done: bool = False


@runtime_checkable
class LLMBackend(Protocol):
    def chat_stream(
        self,
        messages: list[Message],
        *,
        thinking: bool = False,
    ) -> AsyncIterator[LLMChunk]:
        """Return an async iterator that streams LLMChunks.

        Concrete implementations are typically ``async def`` generator
        functions — calling an async generator function returns the
        generator synchronously, so the Protocol is declared with a
        plain ``def``.
        """
        ...
