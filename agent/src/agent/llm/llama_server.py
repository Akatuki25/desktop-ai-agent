"""LlamaServerBackend — talks to llama-server's OpenAI-compatible API.

Covers only the streaming chat.completions path; tool calling lands in
a later phase. We let llama.cpp's built-in Hermes parser handle the
heavy lifting for Qwen3 on its end and just stream raw text back here.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from agent.llm.backend import LLMChunk, Message, ToolCallDelta
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
        tools: list[dict[str, object]] | None = None,
        thinking: bool = False,
    ) -> AsyncIterator[LLMChunk]:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": True,
            "temperature": self.temperature,
        }
        if tools:
            payload["tools"] = tools
        if not thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}

        parser = ThinkingStreamParser()

        # Accumulator for streaming tool_calls. llama-server sends them
        # incrementally: first chunk has id+name, subsequent chunks append
        # to arguments. We merge by index and emit on finish_reason=tool_calls.
        pending_tools: dict[int, dict[str, str]] = {}

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
                choice = choices[0]
                delta = choice.get("delta") or {}
                finish = choice.get("finish_reason")

                # --- streaming tool_calls accumulation ---
                tc_list = delta.get("tool_calls") or []
                for tc in tc_list:
                    idx = tc.get("index", 0)
                    if idx not in pending_tools:
                        pending_tools[idx] = {
                            "id": tc.get("id", ""),
                            "name": (tc.get("function") or {}).get("name", ""),
                            "arguments": "",
                        }
                    args_piece = (tc.get("function") or {}).get("arguments", "")
                    if args_piece:
                        pending_tools[idx]["arguments"] += args_piece
                    # Capture the id if it comes in a later chunk.
                    if tc.get("id"):
                        pending_tools[idx]["id"] = tc["id"]
                    fn = (tc.get("function") or {}).get("name")
                    if fn:
                        pending_tools[idx]["name"] = fn

                if finish == "tool_calls" and pending_tools:
                    calls = [
                        ToolCallDelta(
                            id=t["id"],
                            name=t["name"],
                            arguments_json=t["arguments"],
                        )
                        for t in pending_tools.values()
                    ]
                    yield LLMChunk(text="", tool_calls=calls)
                    pending_tools.clear()
                    continue

                # --- reasoning_content (thinking) ---
                reasoning = delta.get("reasoning_content") or ""
                if reasoning:
                    yield LLMChunk(text=reasoning, is_thinking=True)

                # --- regular content ---
                piece = delta.get("content") or ""
                if not piece:
                    continue
                for emit, is_thinking in parser.feed(piece):
                    yield LLMChunk(text=emit, is_thinking=is_thinking)

        for emit, is_thinking in parser.flush():
            yield LLMChunk(text=emit, is_thinking=is_thinking)
        yield LLMChunk(text="", done=True)
