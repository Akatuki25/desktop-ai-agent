"""Voice pipeline — STT in, TurnLoop out (half-duplex).

Wires the streaming STT client to the existing text-mode TurnLoop in
"voice mode": once the user opens the session it stays open until they
explicitly close it, and Deepgram's native VAD events drive the turn
boundaries.

    [mic PCM] → DeepgramSTT
                  ├── Results (interim) → partial_callback (live captions)
                  ├── Results (final)   → buffered into _final_segments
                  ├── UtteranceEnd      → fire TurnLoop on the buffered text
                  └── SpeechStarted     → (half-duplex: ignored while
                                           agent is speaking; otherwise
                                           reserved for future barge-in)

The desktop pipeline has no echo cancellation, so the agent's own TTS
leaks into the mic and Deepgram detects it as user speech. To prevent
self-interrupt we run half-duplex: while the agent is replying or its
TTS is still playing on the client, mic frames are dropped before
they reach Deepgram. The frontend fires `voice.tts_done` once its
playback queue drains, which clears the gate.

`set_event_callback` receives every TurnEvent that comes out of the
turns this pipeline auto-fires; the WS layer registers it so events
flow to the client identically to the text path. `set_interrupt_callback`
exists for the (disabled in this build) barge-in path.
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
        # Half-duplex gate: while True, mic PCM is dropped before
        # reaching Deepgram. Set when a turn fires, cleared when the
        # client confirms its TTS playback queue has drained
        # (voice.tts_done) or when the turn produced no TTS at all.
        self._agent_audio_pending = False

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
        # Half-duplex: drop mic frames while the agent is replying so
        # our own TTS doesn't echo back through Deepgram. The flag
        # stays set until the client emits voice.tts_done.
        if self._agent_audio_pending:
            return
        await self._stt.feed(pcm)

    def notify_tts_done(self) -> None:
        """Called from the WS layer when the client has finished playing
        all queued TTS audio. Releases the half-duplex mic gate so the
        next user utterance can be captured."""
        self._agent_audio_pending = False

    async def stop_session(self) -> None:
        """Tear down the voice session entirely.

        Cancels any in-flight turn before closing the STT connection, so
        we don't leave a half-streamed reply hanging.
        """
        if not self._active:
            return
        self._active = False
        self._agent_audio_pending = False
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
        """Reserved for barge-in. Half-duplex disables it: while the
        agent is replying, audio is gated upstream so Deepgram should
        not even fire SpeechStarted; if it does (already-buffered
        frames), ignore to avoid self-interrupt."""
        if self._agent_audio_pending:
            return
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
        # Engage the half-duplex gate immediately so that audio captured
        # during the LLM's own latency (between this point and the first
        # TTS chunk) is also dropped — otherwise Deepgram catches the
        # tail of the user's last word and we get an immediate echo
        # SpeechStarted.
        self._agent_audio_pending = True
        self._current_turn = asyncio.create_task(self._run_turn(text))

    # ------------------------------------------------------------------
    # Turn execution
    # ------------------------------------------------------------------

    async def _run_turn(self, text: str) -> None:
        cb = self._event_callback
        emitted_tts = False
        try:
            async for evt in self._turn_loop.run(text):
                if cb is not None:
                    await cb(evt)
                if getattr(evt, "kind", None) == "tts":
                    emitted_tts = True
        except asyncio.CancelledError:
            # The LLM stream and any downstream TTS tear down via the
            # cancellation chain. Release the mic immediately — there's
            # no audio left to drain.
            self._agent_audio_pending = False
            raise
        except Exception as e:
            sys.stderr.write(f"[voice] turn error: {e}\n")
            self._agent_audio_pending = False
            return
        # If the turn never produced TTS (text-only reply, tool result),
        # the client won't send voice.tts_done — clear the gate now so
        # we don't strand the user behind a permanent mute.
        if not emitted_tts:
            self._agent_audio_pending = False

    async def _cancel_current_turn(self) -> None:
        task = self._current_turn
        if task is None or task.done():
            self._current_turn = None
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        self._current_turn = None
