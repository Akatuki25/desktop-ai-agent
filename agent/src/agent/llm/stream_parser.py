"""Split <think>...</think> out of a streaming text feed.

Qwen3 emits thinking as a prefix envelope; llama.cpp's Hermes parser
leaves the literal tags in the assistant content stream when thinking
mode is on. We run every incoming chunk through this small state
machine so the orchestrator can emit is_thinking=True deltas to the
UI's secondary bubble layer.

The parser only looks at the two literal tags. Partial tag prefixes
that span chunk boundaries are buffered until they can be resolved.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

OPEN = "<think>"
CLOSE = "</think>"


@dataclass
class ThinkingStreamParser:
    """Stateful parser; feed chunks in, get (text, is_thinking) pairs out."""

    _in_thinking: bool = False
    _buffer: str = field(default="")

    def feed(self, chunk: str) -> Iterator[tuple[str, bool]]:
        """Yield (emit_text, is_thinking) for each resolved segment.

        May yield zero segments if the chunk is entirely buffered waiting
        for a tag boundary to disambiguate.
        """
        self._buffer += chunk

        while self._buffer:
            if self._in_thinking:
                idx = self._buffer.find(CLOSE)
                if idx == -1:
                    # No closing tag yet — but we must not emit a partial
                    # CLOSE prefix. Hold back the last len(CLOSE)-1 chars.
                    emit_len = max(0, len(self._buffer) - (len(CLOSE) - 1))
                    if emit_len:
                        yield (self._buffer[:emit_len], True)
                        self._buffer = self._buffer[emit_len:]
                    return
                if idx > 0:
                    yield (self._buffer[:idx], True)
                self._buffer = self._buffer[idx + len(CLOSE) :]
                self._in_thinking = False
            else:
                idx = self._buffer.find(OPEN)
                if idx == -1:
                    # No opening tag — emit everything except a possible
                    # partial-tag tail.
                    emit_len = max(0, len(self._buffer) - (len(OPEN) - 1))
                    if emit_len:
                        yield (self._buffer[:emit_len], False)
                        self._buffer = self._buffer[emit_len:]
                    return
                if idx > 0:
                    yield (self._buffer[:idx], False)
                self._buffer = self._buffer[idx + len(OPEN) :]
                self._in_thinking = True

    def flush(self) -> Iterator[tuple[str, bool]]:
        """Emit anything still in the buffer at stream end."""
        if self._buffer:
            yield (self._buffer, self._in_thinking)
            self._buffer = ""
