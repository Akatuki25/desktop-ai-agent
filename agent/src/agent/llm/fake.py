"""Test double / offline-demo backend.

Two modes:

- ``FakeLLMBackend("some text")`` streams that fixed string for every
  call. Used by unit tests so they don't need a real model.
- ``FakeLLMBackend.persona()`` returns a backend that echoes the last
  user turn with a tiny canned envelope so the Tauri window has
  *something* to talk to while the 5GB Qwen3 GGUF is still downloading.

Calling an ``async def`` generator function returns an async generator
synchronously, which is why LLMBackend's Protocol declares
``chat_stream`` with a plain ``def``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from agent.llm.backend import LLMChunk, Message
from agent.llm.stream_parser import ThinkingStreamParser


class FakeLLMBackend:
    def __init__(
        self,
        scripted_response: str | None = None,
        *,
        chunk_size: int = 4,
        persona: bool = False,
    ) -> None:
        self.scripted_response = scripted_response
        self.chunk_size = chunk_size
        self.persona = persona
        self.last_messages: list[Message] = []

    @classmethod
    def persona_mode(cls) -> FakeLLMBackend:
        return cls(persona=True)

    def _response_for(self, messages: list[Message]) -> str:
        if self.scripted_response is not None:
            return self.scripted_response
        # Persona-mode: glance at the most recent user turn and produce a
        # short Japanese response that makes the UI pipe feel alive.
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        if not last_user:
            return "こんにちは。まだ何も受け取っていません。"
        # Split thinking from the user-visible reply so the bubble's
        # thinking layer has content to render.
        return (
            f"<think>ユーザーの発言: {last_user!r}</think>"
            f"（オフラインのダミー応答）「{last_user}」を受け取りました。"
            "本物のLLMを使うには llama-server を起動して"
            " AGENT_LLM_BACKEND=llama_server にしてください。"
        )

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        thinking: bool = False,
    ) -> AsyncIterator[LLMChunk]:
        self.last_messages = list(messages)
        parser = ThinkingStreamParser()
        text = self._response_for(messages)
        for i in range(0, len(text), self.chunk_size):
            raw = text[i : i + self.chunk_size]
            for emit, is_thinking in parser.feed(raw):
                yield LLMChunk(text=emit, is_thinking=is_thinking)
        for emit, is_thinking in parser.flush():
            yield LLMChunk(text=emit, is_thinking=is_thinking)
        yield LLMChunk(text="", done=True)
