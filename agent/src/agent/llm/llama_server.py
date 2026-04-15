"""LlamaServerBackend — talks to llama-server's OpenAI-compatible API.

Covers only the streaming chat.completions path; tool calling lands in
a later phase. We let llama.cpp's built-in Hermes parser handle the
heavy lifting for Qwen3 on its end and just stream raw text back here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from agent.llm.backend import LLMChunk, Message
from agent.llm.stream_parser import ThinkingStreamParser


class LlamaServerBackend:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        *,
        model: str = "qwen",
        temperature: float = 0.7,
        timeout_s: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.timeout_s = timeout_s
        self._transport = transport

    def _make_client(self) -> httpx.AsyncClient:
        if self._transport is not None:
            return httpx.AsyncClient(transport=self._transport, timeout=self.timeout_s)
        return httpx.AsyncClient(timeout=self.timeout_s)

    async def chat_stream(
        self,
        messages: list[Message],
        *,
        thinking: bool = False,
    ) -> AsyncIterator[LLMChunk]:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "temperature": self.temperature,
        }
        if not thinking:
            # Qwen3 soft-switch: inline directive the model recognises.
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        parser = ThinkingStreamParser()

        async with (
            self._make_client() as client,
            client.stream(
                "POST",
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}

                # Newer llama.cpp (b8000+) splits Qwen-style thinking into a
                # dedicated `reasoning_content` field instead of leaving the
                # <think>...</think> envelope inline. Emit those tokens
                # directly as is_thinking=True so the bubble's secondary
                # layer still receives them; do NOT run them through the
                # tag parser (no envelope to parse).
                reasoning = delta.get("reasoning_content") or ""
                if reasoning:
                    yield LLMChunk(text=reasoning, is_thinking=True)

                piece = delta.get("content") or ""
                if not piece:
                    continue
                # `content` may still contain inline <think> tags on older
                # builds — keep the parser path for that case.
                for emit, is_thinking in parser.feed(piece):
                    yield LLMChunk(text=emit, is_thinking=is_thinking)

        for emit, is_thinking in parser.flush():
            yield LLMChunk(text=emit, is_thinking=is_thinking)
        yield LLMChunk(text="", done=True)
