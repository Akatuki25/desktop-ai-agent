"""Tests for the voice pipeline (STT client + pipeline glue).

These don't talk to Deepgram — they substitute a fake WebSocket
connection that emits canned JSON results, so the contract we
care about (parse → dispatch → propagate is_final, plus the new
SpeechStarted / UtteranceEnd routing) is exercised without a network
or API key.
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


@pytest.mark.asyncio
async def test_stt_routes_speech_started_and_utterance_end(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SpeechStarted / UtteranceEnd are the events that drive barge-in
    and turn-fire — they must reach the dedicated callbacks."""
    scripted = [
        json.dumps({"type": "SpeechStarted", "timestamp": 0.5}),
        json.dumps(
            {
                "type": "Results",
                "is_final": True,
                "channel": {"alternatives": [{"transcript": "やあ"}]},
            }
        ),
        json.dumps({"type": "UtteranceEnd", "last_word_end": 1.2}),
    ]
    fake = _FakeDeepgramWS(scripted)

    async def fake_connect(*_a: Any, **_kw: Any) -> _FakeDeepgramWS:
        return fake

    monkeypatch.setattr(stt_mod.websockets, "connect", fake_connect)

    transcripts: list[tuple[str, bool]] = []
    speech_started_count = 0
    utterance_end_count = 0

    async def on_transcript(t: str, f: bool) -> None:
        transcripts.append((t, f))

    async def on_speech_started() -> None:
        nonlocal speech_started_count
        speech_started_count += 1

    async def on_utterance_end() -> None:
        nonlocal utterance_end_count
        utterance_end_count += 1

    stt = DeepgramSTT(api_key="x")
    await stt.start(
        on_transcript,
        on_speech_started=on_speech_started,
        on_utterance_end=on_utterance_end,
    )
    await asyncio.sleep(0.05)
    await stt.stop()

    assert transcripts == [("やあ", True)]
    assert speech_started_count == 1
    assert utterance_end_count == 1


def test_stt_url_includes_vad_events_and_utterance_end() -> None:
    """vad_events + utterance_end_ms are required for barge-in to work
    at all — pin them so a regression on the URL string is caught."""
    stt = DeepgramSTT(api_key="x", utterance_end_ms=1000)
    assert "vad_events=true" in stt._url
    assert "utterance_end_ms=1000" in stt._url


def test_stt_requires_api_key() -> None:
    with pytest.raises(ValueError):
        DeepgramSTT(api_key="")


# --------------------------------------------------------------------------
# VoicePipeline: orchestration on top of STT + TurnLoop
# --------------------------------------------------------------------------


class _FakeSTT:
    """Stands in for DeepgramSTT — records calls, lets us drive
    transcripts and VAD events directly."""

    def __init__(self) -> None:
        self.started = False
        self.stopped = False
        self.fed: list[bytes] = []
        self._on_transcript: Any = None
        self._on_speech_started: Any = None
        self._on_utterance_end: Any = None

    async def start(
        self,
        callback: Any,
        *,
        on_speech_started: Any = None,
        on_utterance_end: Any = None,
    ) -> None:
        self.started = True
        self._on_transcript = callback
        self._on_speech_started = on_speech_started
        self._on_utterance_end = on_utterance_end

    async def feed(self, pcm: bytes) -> None:
        self.fed.append(pcm)

    async def stop(self) -> None:
        self.stopped = True

    async def emit(self, text: str, is_final: bool) -> None:
        if self._on_transcript is None:
            raise RuntimeError("emit before start")
        await self._on_transcript(text, is_final)

    async def emit_speech_started(self) -> None:
        if self._on_speech_started is None:
            raise RuntimeError("speech_started before start")
        await self._on_speech_started()

    async def emit_utterance_end(self) -> None:
        if self._on_utterance_end is None:
            raise RuntimeError("utterance_end before start")
        await self._on_utterance_end()


class _FakeTurnLoop:
    def __init__(self, reply: str) -> None:
        self.received: list[str] = []
        self._reply = reply

    async def run(self, user_text: str) -> AsyncIterator[Any]:
        self.received.append(user_text)
        yield SayEvent(kind="delta", text=self._reply)
        yield SayEvent(kind="end", message_id="msg")


class _SlowTurnLoop:
    """Turn loop that yields one delta then sleeps long enough that an
    interrupting cancel can land before it would have completed."""

    def __init__(self) -> None:
        self.received: list[str] = []
        self.completed = False

    async def run(self, user_text: str) -> AsyncIterator[Any]:
        self.received.append(user_text)
        yield SayEvent(kind="delta", text="hmm")
        await asyncio.sleep(1.0)  # plenty of room for a cancel
        yield SayEvent(kind="end", message_id="late")
        self.completed = True


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
    assert "こんにちは" not in partials


@pytest.mark.asyncio
async def test_pipeline_utterance_end_fires_turn_via_event_callback() -> None:
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="どうしたのだ？")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    events: list[Any] = []

    async def on_event(evt: Any) -> None:
        events.append(evt)

    pipeline.set_event_callback(on_event)
    await pipeline.start_session()
    await stt.emit("やあ", is_final=True)
    await stt.emit("元気？", is_final=True)
    await stt.emit_utterance_end()

    # Wait for the turn task to drain.
    for _ in range(50):
        if len(events) >= 2:
            break
        await asyncio.sleep(0.01)

    assert turn_loop.received == ["やあ 元気？"]
    assert [e.kind for e in events] == ["delta", "end"]

    await pipeline.stop_session()
    assert stt.stopped


@pytest.mark.asyncio
async def test_pipeline_utterance_end_with_no_final_is_noop() -> None:
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="x")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    events: list[Any] = []

    async def on_event(evt: Any) -> None:
        events.append(evt)

    pipeline.set_event_callback(on_event)
    await pipeline.start_session()
    # No interim/final transcripts before the utterance ends → ignored.
    await stt.emit_utterance_end()
    await asyncio.sleep(0.05)

    assert events == []
    assert turn_loop.received == []

    await pipeline.stop_session()


@pytest.mark.asyncio
async def test_pipeline_speech_started_cancels_in_flight_turn() -> None:
    """Barge-in: once the user starts a new utterance, the in-flight
    reply is cancelled and the interrupt callback fires."""
    stt = _FakeSTT()
    turn_loop = _SlowTurnLoop()
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    events: list[Any] = []
    interrupts = 0

    async def on_event(evt: Any) -> None:
        events.append(evt)

    async def on_interrupt() -> None:
        nonlocal interrupts
        interrupts += 1

    pipeline.set_event_callback(on_event)
    pipeline.set_interrupt_callback(on_interrupt)
    await pipeline.start_session()

    # First utterance fires a turn.
    await stt.emit("hi", is_final=True)
    await stt.emit_utterance_end()
    # Wait until the slow turn has emitted its first delta.
    for _ in range(100):
        if events:
            break
        await asyncio.sleep(0.01)
    assert events and events[0].kind == "delta"

    # User starts talking again → barge-in.
    await stt.emit_speech_started()
    # Give the cancel + interrupt callback time to land.
    await asyncio.sleep(0.05)

    assert interrupts == 1
    assert not turn_loop.completed
    # No "end" event should have arrived because the turn was cancelled.
    assert all(e.kind != "end" for e in events)

    await pipeline.stop_session()


@pytest.mark.asyncio
async def test_pipeline_speech_started_without_in_flight_turn_does_nothing() -> None:
    """A SpeechStarted with no current reply (e.g. very first turn) is
    not an interrupt — the callback should not fire."""
    stt = _FakeSTT()
    turn_loop = _FakeTurnLoop(reply="x")
    pipeline = VoicePipeline(stt=stt, turn_loop=turn_loop)  # type: ignore[arg-type]

    interrupts = 0

    async def on_interrupt() -> None:
        nonlocal interrupts
        interrupts += 1

    pipeline.set_interrupt_callback(on_interrupt)
    await pipeline.start_session()

    await stt.emit_speech_started()
    await asyncio.sleep(0.02)

    assert interrupts == 0
    await pipeline.stop_session()


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

    await pipeline.stop_session()
