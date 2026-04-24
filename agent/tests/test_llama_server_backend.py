"""LlamaServerBackend HTTP-level tests.

These mock the streaming /v1/chat/completions endpoint so we exercise
the real HTTP plumbing without booting llama-server. The fake LLM
backend does not catch protocol regressions — that's why these exist.

Two representative response shapes are covered:

1. Inline <think> envelope (older llama.cpp builds, content-only)
2. delta.reasoning_content split out (llama.cpp b8000+ behaviour)

A regression in either path silently drops thinking text, so each test
asserts both the main and thinking buffers end up correct.
"""

from __future__ import annotations

import httpx
import pytest

from agent.llm import LlamaServerBackend
from agent.llm.backend import Message


def _sse_lines(events: list[str]) -> bytes:
    return ("\n".join(f"data: {e}" for e in events) + "\n").encode("utf-8")


@pytest.mark.asyncio
async def test_inline_think_envelope_is_split() -> None:
    body = _sse_lines(
        [
            '{"choices":[{"delta":{"content":"<think>plan"}}]}',
            '{"choices":[{"delta":{"content":"ning</think>hel"}}]}',
            '{"choices":[{"delta":{"content":"lo"}}]}',
            "[DONE]",
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        # Sanity: thinking is sent disabled by default.
        assert b'"enable_thinking":false' in request.content
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    backend = LlamaServerBackend(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )

    main: list[str] = []
    thinking: list[str] = []
    async for chunk in backend.chat_stream([Message(role="user", content="hi")]):
        if chunk.done:
            break
        (thinking if chunk.is_thinking else main).append(chunk.text)

    assert "".join(thinking) == "planning"
    assert "".join(main) == "hello"


@pytest.mark.asyncio
async def test_reasoning_content_field_is_routed_to_thinking_buffer() -> None:
    body = _sse_lines(
        [
            '{"choices":[{"delta":{"reasoning_content":"thinking step 1"}}]}',
            '{"choices":[{"delta":{"reasoning_content":" step 2"}}]}',
            '{"choices":[{"delta":{"content":"final answer"}}]}',
            "[DONE]",
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=body,
            headers={"content-type": "text/event-stream"},
        )

    backend = LlamaServerBackend(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )

    main: list[str] = []
    thinking: list[str] = []
    async for chunk in backend.chat_stream([Message(role="user", content="hi")]):
        if chunk.done:
            break
        (thinking if chunk.is_thinking else main).append(chunk.text)

    # Regression guard: prior implementation only read delta.content and
    # silently dropped reasoning_content. If that reverts, this assertion
    # will fail with empty `thinking`.
    assert "".join(thinking) == "thinking step 1 step 2"
    assert "".join(main) == "final answer"


@pytest.mark.asyncio
async def test_done_sentinel_terminates_stream() -> None:
    body = _sse_lines(
        [
            '{"choices":[{"delta":{"content":"hi"}}]}',
            "[DONE]",
            '{"choices":[{"delta":{"content":"never"}}]}',
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    backend = LlamaServerBackend(
        base_url="http://test",
        transport=httpx.MockTransport(handler),
    )

    pieces: list[str] = []
    async for chunk in backend.chat_stream([Message(role="user", content="x")]):
        if chunk.done:
            break
        pieces.append(chunk.text)
    assert "".join(pieces) == "hi"
