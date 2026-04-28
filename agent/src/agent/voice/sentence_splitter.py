"""Incremental sentence splitter for streaming TTS.

The orchestrator streams LLM tokens as they arrive. We feed each
delta into this splitter, which buffers characters until it hits a
sentence boundary, then yields the complete sentence (which the
TTS engine can immediately synthesize).

Boundaries: Japanese 「。」「！」「？」 + English ``. ! ?`` followed
by whitespace or end-of-buffer. Newlines also count so list items
get spoken one at a time.

Short fragments (under MIN_CHARS) are merged into the next sentence
to avoid VOICEVOX-spawn-overhead per token.
"""

from __future__ import annotations

from collections.abc import Iterator

# Japanese full-stop, exclamation, question + ASCII counterparts.
_TERMINATORS = set("。！？.!?")
_MIN_CHARS = 5  # don't synthesize fragments shorter than this


class SentenceSplitter:
    def __init__(self, *, min_chars: int = _MIN_CHARS) -> None:
        self._buf: list[str] = []
        self._buf_len: int = 0
        self._min_chars = min_chars

    def feed(self, text: str) -> Iterator[str]:
        """Yield complete sentences as they cross a boundary."""
        if not text:
            return
        for ch in text:
            self._buf.append(ch)
            self._buf_len += 1
            if ch in _TERMINATORS and self._buf_len >= self._min_chars:
                yield "".join(self._buf).strip()
                self._buf.clear()
                self._buf_len = 0
            elif ch == "\n" and self._buf_len >= self._min_chars:
                fragment = "".join(self._buf).strip()
                self._buf.clear()
                self._buf_len = 0
                if fragment:
                    yield fragment

    def flush(self) -> str:
        """Return whatever is left in the buffer at stream end."""
        if not self._buf:
            return ""
        out = "".join(self._buf).strip()
        self._buf.clear()
        self._buf_len = 0
        return out
