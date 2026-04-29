"""Deepgram streaming STT client.

Talks to Deepgram's realtime WebSocket API directly (no SDK) so the
dependency footprint stays at the websockets package we already
have. The expected audio format is 16-bit PCM little-endian, 16 kHz,
mono — that's what the frontend's micCapture produces.

The class owns three things:
    1. an outgoing connection that we feed PCM into
    2. a background task that reads JSON results and pushes them
       to a caller-supplied callback
    3. an explicit stop() that closes both halves cleanly

Deepgram's WS protocol (relevant subset):
    - send raw audio bytes as binary frames
    - receive JSON like
        {"type": "Results",
         "is_final": true,
         "channel": {"alternatives": [{"transcript": "...", ...}]}}
    - send {"type": "CloseStream"} to flush and close

We accept partial (interim) results so the UI can render live
captions while the user is still talking; the caller distinguishes
final from interim via the is_final flag.
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


class DeepgramSTT:
    def __init__(
        self,
        api_key: str,
        *,
        language: str = "ja",
        model: str = "nova-2",
        sample_rate: int = 16000,
    ) -> None:
        if not api_key:
            raise ValueError("Deepgram API key is required")
        self._api_key = api_key
        self._language = language
        self._model = model
        self._sample_rate = sample_rate
        self._ws: ClientConnection | None = None
        self._reader: asyncio.Task[None] | None = None
        self._callback: TranscriptCallback | None = None

    @property
    def _url(self) -> str:
        # linear16 = signed 16-bit PCM little-endian, which is what the
        # frontend's Float32→Int16 conversion produces.
        return (
            "wss://api.deepgram.com/v1/listen"
            f"?language={self._language}"
            f"&model={self._model}"
            f"&sample_rate={self._sample_rate}"
            "&channels=1"
            "&encoding=linear16"
            "&punctuate=true"
            "&interim_results=true"
        )

    async def start(self, callback: TranscriptCallback) -> None:
        if self._ws is not None:
            return  # already running
        self._callback = callback
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
        self._callback = None
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
                if msg.get("type") != "Results":
                    continue
                channel = msg.get("channel") or {}
                alts = channel.get("alternatives") or []
                if not alts:
                    continue
                transcript = (alts[0].get("transcript") or "").strip()
                if not transcript:
                    continue
                is_final = bool(msg.get("is_final"))
                cb = self._callback
                if cb is None:
                    continue
                try:
                    await cb(transcript, is_final)
                except Exception as e:
                    sys.stderr.write(f"[stt] callback error: {e}\n")
        except websockets.ConnectionClosed:
            return
        except Exception as e:
            sys.stderr.write(f"[stt] read loop error: {e}\n")
