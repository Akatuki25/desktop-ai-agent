"""Deepgram streaming STT client.

Talks to Deepgram's realtime WebSocket API directly (no SDK) so the
dependency footprint stays at the websockets package we already
have. The expected audio format is 16-bit PCM little-endian, 16 kHz,
mono — that's what the frontend's micCapture produces.

The class exposes 3 callback hooks so the upstream VoicePipeline can
build a barge-in-capable conversational loop without touching JSON:
    - on_transcript(text, is_final): live captions + final segments
    - on_speech_started(): user started talking → cancel any in-flight
      reply (barge-in)
    - on_utterance_end(): user finished a thought → fire the turn

Deepgram emits SpeechStarted / UtteranceEnd natively when we set
`vad_events=true` and `utterance_end_ms=<N>` on the connect URL,
which removes any need for client-side VAD heuristics.

Wire protocol (relevant subset):
    - send raw audio bytes as binary frames
    - receive JSON
        {"type":"Results", "is_final": true,
         "speech_final": true,
         "channel":{"alternatives":[{"transcript":"..."}]}}
        {"type":"SpeechStarted", "timestamp": ...}
        {"type":"UtteranceEnd", "last_word_end": ...}
    - send {"type": "CloseStream"} to flush and close
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection

TranscriptCallback = Callable[[str, bool], Awaitable[None]]
EventCallback = Callable[[], Awaitable[None]]


class DeepgramSTT:
    def __init__(
        self,
        api_key: str,
        *,
        language: str = "ja",
        model: str = "nova-2",
        sample_rate: int = 16000,
        utterance_end_ms: int = 1000,
    ) -> None:
        if not api_key:
            raise ValueError("Deepgram API key is required")
        self._api_key = api_key
        self._language = language
        self._model = model
        self._sample_rate = sample_rate
        self._utterance_end_ms = utterance_end_ms
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._on_transcript: TranscriptCallback | None = None
        self._on_speech_started: EventCallback | None = None
        self._on_utterance_end: EventCallback | None = None

    @property
    def _url(self) -> str:
        # linear16 = signed 16-bit PCM little-endian, which is what the
        # frontend's Float32→Int16 conversion produces. vad_events +
        # utterance_end_ms make Deepgram emit SpeechStarted /
        # UtteranceEnd, which is what enables natural turn-taking and
        # barge-in without any local VAD.
        return (
            "wss://api.deepgram.com/v1/listen"
            f"?language={self._language}"
            f"&model={self._model}"
            f"&sample_rate={self._sample_rate}"
            "&channels=1"
            "&encoding=linear16"
            "&punctuate=true"
            "&interim_results=true"
            "&vad_events=true"
            f"&utterance_end_ms={self._utterance_end_ms}"
        )

    async def start(
        self,
        callback: TranscriptCallback,
        *,
        on_speech_started: EventCallback | None = None,
        on_utterance_end: EventCallback | None = None,
    ) -> None:
        if self._ws is not None:
            return  # already running
        self._on_transcript = callback
        self._on_speech_started = on_speech_started
        self._on_utterance_end = on_utterance_end
        self._ws = await websockets.connect(
            self._url,
            additional_headers={"Authorization": f"Token {self._api_key}"},
            max_size=None,
        )
        self._reader = asyncio.create_task(self._read_loop())

    async def feed(self, pcm_bytes: bytes) -> None:
        if self._ws is None:
            return
        try:
            await self._ws.send(pcm_bytes)
        except Exception as e:
            sys.stderr.write(f"[stt] feed failed: {e}\n")

    async def stop(self) -> None:
        ws = self._ws
        reader = self._reader
        self._ws = None
        self._reader = None
        self._on_transcript = None
        self._on_speech_started = None
        self._on_utterance_end = None
        if ws is None:
            return
        # Tell Deepgram to flush and finalize.
        with contextlib.suppress(Exception):
            await ws.send(json.dumps({"type": "CloseStream"}))
        # Give the reader a moment to drain any final results.
        if reader is not None:
            try:
                await asyncio.wait_for(reader, timeout=3.0)
            except TimeoutError:
                reader.cancel()
            except Exception:
                pass
        with contextlib.suppress(Exception):
            await ws.close()

    async def _read_loop(self) -> None:
        ws = self._ws
        if ws is None:
            return
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue  # we don't expect binary back
                try:
                    msg: dict[str, Any] = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                if msg_type == "Results":
                    await self._handle_results(msg)
                elif msg_type == "SpeechStarted":
                    await self._fire(self._on_speech_started, "speech_started")
                elif msg_type == "UtteranceEnd":
                    await self._fire(self._on_utterance_end, "utterance_end")
                # Ignore Metadata, Open, Close, etc.
        except websockets.ConnectionClosed:
            return
        except Exception as e:
            sys.stderr.write(f"[stt] read loop error: {e}\n")

    async def _handle_results(self, msg: dict[str, Any]) -> None:
        channel = msg.get("channel") or {}
        alts = channel.get("alternatives") or []
        if not alts:
            return
        transcript = (alts[0].get("transcript") or "").strip()
        if not transcript:
            return
        is_final = bool(msg.get("is_final"))
        cb = self._on_transcript
        if cb is None:
            return
        try:
            await cb(transcript, is_final)
        except Exception as e:
            sys.stderr.write(f"[stt] transcript callback error: {e}\n")

    async def _fire(
        self, cb: EventCallback | None, label: str
    ) -> None:
        if cb is None:
            return
        try:
            await cb()
        except Exception as e:
            sys.stderr.write(f"[stt] {label} callback error: {e}\n")
