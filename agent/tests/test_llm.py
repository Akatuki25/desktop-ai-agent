"""LLM backend + stream parser tests.

llama-server is not exercised here (integration tests would spawn a
real process). The parser has its own dedicated table-ish cases and
the FakeLLMBackend round-trip covers the async shape.
"""

from __future__ import annotations

import pytest

from agent.llm import FakeLLMBackend, Message, ThinkingStreamParser


def _drive(parser: ThinkingStreamParser, chunks: list[str]) -> list[tuple[str, bool]]:
    """Run chunks through parser and collapse adjacent same-type segments.

    The parser is free to emit partial fragments of a single logical
    segment as it holds bytes back waiting for tag disambiguation; the
    consumer (orchestrator) doesn't care because it concatenates
    deltas. Tests assert on the collapsed form so they stay focused on
    tag boundaries, not on fragmentation.
    """
    raw: list[tuple[str, bool]] = []
    for c in chunks:
        raw.extend(parser.feed(c))
    raw.extend(parser.flush())
    merged: list[tuple[str, bool]] = []
    for text, is_thinking in raw:
        if merged and merged[-1][1] == is_thinking:
            merged[-1] = (merged[-1][0] + text, is_thinking)
        else:
            merged.append((text, is_thinking))
    return merged


def test_parser_plain_text_passthrough() -> None:
    assert _drive(ThinkingStreamParser(), ["hello ", "world"]) == [
        ("hello world", False),
    ]


def test_parser_extracts_thinking_block() -> None:
    segments = _drive(
        ThinkingStreamParser(),
        ["<think>considering...</think>final answer"],
    )
    assert segments == [
        ("considering...", True),
        ("final answer", False),
    ]


def test_parser_handles_tag_split_across_chunks() -> None:
    segments = _drive(
        ThinkingStreamParser(),
        ["pre<thi", "nk>inside</thi", "nk>post"],
    )
    assert segments == [
        ("pre", False),
        ("inside", True),
        ("post", False),
    ]


def test_parser_flushes_unterminated_thinking() -> None:
    segments = _drive(
        ThinkingStreamParser(),
        ["<think>still thinking"],
    )
    assert segments == [("still thinking", True)]


def test_parser_handles_multiple_blocks() -> None:
    segments = _drive(
        ThinkingStreamParser(),
        ["<think>a</think>b<think>c</think>d"],
    )
    assert segments == [("a", True), ("b", False), ("c", True), ("d", False)]


@pytest.mark.asyncio
async def test_fake_backend_streams_and_reports_done() -> None:
    backend = FakeLLMBackend("hello world", chunk_size=3)
    chunks = []
    async for c in backend.chat_stream([Message(role="user", content="hi")]):
        chunks.append(c)
    assert chunks[-1].done is True
    text_parts = [c.text for c in chunks if not c.done]
    assert "".join(text_parts) == "hello world"
    assert all(c.is_thinking is False for c in chunks)
    assert backend.last_messages[0].content == "hi"


@pytest.mark.asyncio
async def test_fake_backend_passes_through_thinking_block() -> None:
    backend = FakeLLMBackend("<think>plan</think>answer", chunk_size=5)
    thinking: list[str] = []
    main: list[str] = []
    async for c in backend.chat_stream([Message(role="user", content="x")]):
        if c.done:
            continue
        (thinking if c.is_thinking else main).append(c.text)
    assert "".join(thinking) == "plan"
    assert "".join(main) == "answer"
