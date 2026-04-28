"""Tests for the voice pipeline (STT client + pipeline glue).

These don't talk to Deepgram — they substitute a fake WebSocket
connection that emits canned JSON results, so the contract we
care about (parse → dispatch → propagate is_final) is exercised
without a network or API key.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from agent.orchestrator.turn_loop import SayEvent
from agent.voice import stt_deepgram as stt_mod
from agent.voice.pipeline import VoicePipeline
from agent.voice.stt_deepgram import DeepgramSTT


class _FakeDeepgramWS:
    """Minimal stand-in for websockets.asyncio.client.ClientConnection.

    Yields a scripted sequence of messages from `__aiter__` (matching
    Deepgram's wire format) and records what was sent.
    """

    def __init__(self, scripted: list[str]) -> None:
        self._scripted = scripted
        self.sent: list[Any] = []
        self.closed = False

    async def send(self, payload: Any) -> None:
        self.sent.append(payload)

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[str]:
        async def gen() -> AsyncIterator[str]:
            for msg in self._scripted:
                # Yield control so the caller can interleave feed() calls.
                await asyncio.sleep(0)
                yield msg

        return gen()


@pytest.mark.asyncio
async def test_stt_routes_partial_and_final(monkeypatch: pytest.MonkeyPatch) -> None:
    scripted = [
        json.dumps(
            {
                "type": "Results",
                "is_final": False,
                "channel": {"alternatives": [{"transcript": "こんに"}]},
            }
        ),
        json.dumps(
            {
                "type": "Results",
                "is_final": True,
                "channel": {"alternatives": [{"transcript": "こんにちは"}]},
            }
        ),
    ]
    fake = _FakeDeepgramWS(scripted)

    async def fake_connect(*_a: Any, **_kw: Any) -> _FakeDeepgramWS:
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)

    received: list[tuple[str, bool]] = []

    async def cb(text: str, is_final: bool) -> None:
        received.append((text, is_final))

    stt = DeepgramSTT(api_key="test-key")
    await stt.start(cb)
    # Push some PCM — the fake records it.
    await stt.feed(b"\x00\x01" * 100)
    # Let the read loop drain.
    await asyncio.sleep(0.05)
    await stt.stop()

    assert received == [("こんに", False), ("こんにちは", True)]
    # The PCM was forwarded, and the CloseStream control message was sent.
    assert b"\x00\x01" * 100 in fake.sent
    assert any(
        isinstance(s, str) and "CloseStream" in s for s in fake.sent
    )


@pytest.mark.asyncio
async def test_stt_skips_empty_transcript(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deepgram emits empty interims while silence is detected; those
    # shouldn't reach the callback.
    scripted = [
        json.dumps(
            {
                "type": "Results",
                "is_final": False,
                "channel": {"alternatives": [{"transcript": "   "}]},
            }
        ),
        json.dumps(
            {
                "type": "Results",
                "is_final": True,
                "channel": {"alternatives": [{"transcript": "ok"}]},
            }
        ),
    ]
    fake = _FakeDeepgramWS(scripted)

    async def fake_connect(*_a: Any, **_kw: Any) -> _FakeDeepgramWS:
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)

    received: list[tuple[str, bool]] = []

    async def cb(text: str, is_final: bool) -> None:
        received.append((text, is_final))

    stt = DeepgramSTT(api_key="x")
    await stt.start(cb)
    await asyncio.sleep(0.05)
    await stt.stop()

    assert received == [("ok", True)]


def test_stt_requires_api_key() -> None:
    with pytest.raises(ValueError):
        DeepgramSTT(api_key="")


# --------------------------------------------------------------------------
# VoicePipeline: orchestration on top of STT + TurnLoop
# --------------------------------------------------------------------------


class _FakeSTT:
    """Stands in for DeepgramSTT — records calls, lets us drive
    transcripts directly via emit()."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.fed: list[bytes] = []
        self._callback: Any = None

    async def start(self, callback: Any) -> None:
        self.started = True
        self._callback = callback

    async def feed(self, pcm: bytes) -> None:
        self.fed.append(pcm)

    async def stop(self) -> None:
        self.stopped = True

    async def emit(self, text: str, is_final: bool) -> None:
        if self._callback is None:
            raise RuntimeError("emit before start")
        await self._callback(text, is_final)


class _FakeTurnLoop:
    def __init__(self, reply: str) -> None:
        self.received_text: str | None = None
        self._reply = reply

    async def run(self, user_text: str) -> AsyncIterator[Any]:
        self.received_text = user_text
        yield SayEvent(kind="delta", text=self._reply)
        yield SayEvent(kind="end", message_id="msg-1")


@pytest.mark.asyncio
async def test_pipeline_partial_callback_fires_only_for_interim() -> None:
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="hi")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    partials: list[str] = []

    async def on_partial(text: str) -> None:
        partials.append(text)

    pipeline.set_partial_callback(on_partial)
    await pipeline.start_session()
    await stt.emit("ko", is_final=False)
    await stt.emit("konnichiwa", is_final=False)
    await stt.emit("こんにちは", is_final=True)

    assert partials == ["ko", "konnichiwa"]
    # Final didn't go through the partial callback.
    assert "こんにちは" not in partials


@pytest.mark.asyncio
async def test_pipeline_stop_runs_final_transcript_through_turnloop() -> None:
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="どうしたのだ？")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    await pipeline.start_session()
    await stt.emit("やあ", is_final=True)
    await stt.emit("元気？", is_final=True)

    events = [evt async for evt in pipeline.stop_session()]

    # STT was stopped, TurnLoop saw the joined transcript, events
    # came through.
    assert stt.stopped
    assert turn_loop.received_text == "やあ 元気？"
    kinds = [e.kind for e in events]
    assert kinds == ["delta", "end"]


@pytest.mark.asyncio
async def test_pipeline_stop_with_no_final_transcript_is_noop() -> None:
    # If the user opens the mic and releases without saying anything
    # final, the pipeline should not run the TurnLoop on an empty string.
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="x")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    await pipeline.start_session()
    events = [evt async for evt in pipeline.stop_session()]

    assert events == []
    assert turn_loop.received_text is None


@pytest.mark.asyncio
async def test_pipeline_feed_audio_routes_to_stt() -> None:
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="x")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    # Before start, feed is a no-op (no STT session open).
    await pipeline.feed_audio(b"\xff\xff")
    assert stt.fed == []

    await pipeline.start_session()
    await pipeline.feed_audio(b"\x01\x02\x03")
    assert stt.fed == [b"\x01\x02\x03"]
