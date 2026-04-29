"""Voice pipeline — STT in, TurnLoop out.

Wires the streaming STT client to the existing text-mode TurnLoop:

    [mic PCM] → DeepgramSTT → transcript → TurnLoop.run(text) → SayEvents
                          ↓
                    partial_callback (live captions)

The frontend pushes a sequence of binary frames while the user holds
the push-to-talk button, then sends voice.stop. Final transcripts
accumulated during the session get joined and dispatched to TurnLoop
exactly like a typed message — every downstream consumer (TTS, tool
calls, persistence) is therefore unchanged from the text path.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Awaitable, Callable

from agent.orchestrator.turn_loop import TurnEvent, TurnLoop
from agent.voice.stt_deepgram import DeepgramSTT

PartialCallback = Callable[[str], Awaitable[None]]


class VoicePipeline:
    def __init__(
        self,
        stt: DeepgramSTT,
        turn_loop: TurnLoop,
    ) -> None:
        self._stt = stt
        self._turn_loop = turn_loop
        self._final_segments: list[str] = []
        self._partial_callback: PartialCallback | None = None
        self._active = False

    def set_partial_callback(self, cb: PartialCallback | None) -> None:
        """Subscribe to interim transcripts. Called by the WS layer to
        forward voice.stt_partial events back to the client."""
        self._partial_callback = cb

    async def start_session(self) -> None:
        if self._active:
            return
        self._final_segments = []
        self._active = True
        await self._stt.start(self._on_transcript)

    async def feed_audio(self, pcm: bytes) -> None:
        if not self._active:
            return
        await self._stt.feed(pcm)

    async def stop_session(self) -> AsyncIterator[TurnEvent]:
        if not self._active:
            return
        await self._stt.stop()
        self._active = False
        text = " ".join(s for s in self._final_segments if s).strip()
        self._final_segments = []
        if not text:
            return
        async for evt in self._turn_loop.run(text):
            yield evt

    async def _on_transcript(self, text: str, is_final: bool) -> None:
        if is_final:
            self._final_segments.append(text)
        else:
            cb = self._partial_callback
            if cb is not None:
                # Partials are best-effort — swallow any client-side error.
                with contextlib.suppress(Exception):
                    await cb(text)
