"""Voice pipeline — STT in, TurnLoop out (with barge-in).

Wires the streaming STT client to the existing text-mode TurnLoop in
"voice mode": once the user opens the session it stays open until they
explicitly close it, and Deepgram's native VAD events drive the turn
boundaries.

    [mic PCM] → DeepgramSTT
                  ├── Results (interim) → partial_callback (live captions)
                  ├── Results (final)   → buffered into _final_segments
                  ├── UtteranceEnd      → fire TurnLoop on the buffered text
                  └── SpeechStarted     → cancel any in-flight turn (barge-in)

`set_event_callback` receives every TurnEvent that comes out of the
turns this pipeline auto-fires; the WS layer registers it so events
flow to the client identically to the text path. `set_interrupt_callback`
fires when the user starts talking over the agent — the WS layer uses
that to broadcast `agent.interrupt` so the frontend can drop pending
TTS audio.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
from collections.abc import Awaitable, Callable

from agent.orchestrator.turn_loop import TurnEvent, TurnLoop
from agent.voice.stt_deepgram import DeepgramSTT

PartialCallback = Callable[[str], Awaitable[None]]
EventCallback = Callable[[TurnEvent], Awaitable[None]]
InterruptCallback = Callable[[], Awaitable[None]]


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
        self._event_callback: EventCallback | None = None
        self._interrupt_callback: InterruptCallback | None = None
        self._active = False
        self._current_turn: asyncio.Task[None] | None = None

    def set_partial_callback(self, cb: PartialCallback | None) -> None:
        """Subscribe to interim transcripts (live captions)."""
        self._partial_callback = cb

    def set_event_callback(self, cb: EventCallback | None) -> None:
        """Subscribe to TurnEvents from auto-fired turns."""
        self._event_callback = cb

    def set_interrupt_callback(self, cb: InterruptCallback | None) -> None:
        """Subscribe to barge-in events (user spoke during a reply)."""
        self._interrupt_callback = cb

    async def start_session(self) -> None:
        if self._active:
            return
        self._final_segments = []
        self._active = True
        await self._stt.start(
            self._on_transcript,
            on_speech_started=self._on_speech_started,
            on_utterance_end=self._on_utterance_end,
        )

    async def feed_audio(self, pcm: bytes) -> None:
        if not self._active:
            return
        await self._stt.feed(pcm)

    async def stop_session(self) -> None:
        """Tear down the voice session entirely.

        Cancels any in-flight turn before closing the STT connection, so
        we don't leave a half-streamed reply hanging.
        """
        if not self._active:
            return
        self._active = False
        await self._cancel_current_turn()
        await self._stt.stop()
        self._final_segments = []

    # ------------------------------------------------------------------
    # STT callbacks
    # ------------------------------------------------------------------

    async def _on_transcript(self, text: str, is_final: bool) -> None:
        if is_final:
            self._final_segments.append(text)
        else:
            cb = self._partial_callback
            if cb is not None:
                # Partials are best-effort — swallow client-side errors.
                with contextlib.suppress(Exception):
                    await cb(text)

    async def _on_speech_started(self) -> None:
        """Barge-in: the user started talking. Cut the agent off."""
        if self._current_turn is not None and not self._current_turn.done():
            await self._cancel_current_turn()
            cb = self._interrupt_callback
            if cb is not None:
                with contextlib.suppress(Exception):
                    await cb()

    async def _on_utterance_end(self) -> None:
        """End-of-utterance: dispatch the buffered transcript as a turn."""
        text = " ".join(s for s in self._final_segments if s).strip()
        self._final_segments = []
        if not text:
            return
        # Clear any lingering interim caption — the utterance is done,
        # so the live "what the user is saying" display should reset
        # before the agent starts replying.
        partial = self._partial_callback
        if partial is not None:
            with contextlib.suppress(Exception):
                await partial("")
        # If a previous turn is somehow still running (e.g. SpeechStarted
        # was missed by Deepgram), cancel it before starting a new one.
        if self._current_turn is not None and not self._current_turn.done():
            await self._cancel_current_turn()
        self._current_turn = asyncio.create_task(self._run_turn(text))

    # ------------------------------------------------------------------
    # Turn execution
    # ------------------------------------------------------------------

    async def _run_turn(self, text: str) -> None:
        cb = self._event_callback
        try:
            async for evt in self._turn_loop.run(text):
                if cb is not None:
                    await cb(evt)
        except asyncio.CancelledError:
            # Barge-in: stop forwarding events. The LLM stream and any
            # downstream TTS will tear down via the cancellation chain.
            raise
        except Exception as e:
            sys.stderr.write(f"[voice] turn error: {e}\n")

    async def _cancel_current_turn(self) -> None:
        task = self._current_turn
        if task is None or task.done():
            self._current_turn = None
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        self._current_turn = None
