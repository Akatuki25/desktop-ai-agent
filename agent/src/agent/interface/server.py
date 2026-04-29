"""FastAPI + WebSocket server wired to the orchestrator.

Phase 0+: session.send_text hands the text to the TurnLoop and streams
each SayEvent back as an `agent.say` JSON-RPC notification, finishing
with `agent.say_end`. If the app is built without an orchestrator
(e.g. unit tests that only care about the WS contract) the server
falls back to the Phase 0 echo behaviour so existing smoke tests
don't regress.

Phase 3: voice methods (voice.start / voice.stop) and binary mic
frames (tag 0x01). voice.start opens a Deepgram STT session, mic
frames feed PCM into it, voice.stop closes the session and runs
the accumulated transcript through the same TurnLoop the text path
uses — so TTS playback, tool calls, and persistence are unchanged.

The server supports two auth mechanisms:
    - Authorization: Bearer <token> header (cmdline/curl clients)
    - Sec-WebSocket-Protocol: bearer.<token>  (browser WebSocket API)
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


class TurnLoopLike(Protocol):
    def run(self, user_text: str) -> AsyncIterator[Any]: ...


class VoicePipelineLike(Protocol):
    async def start_session(self) -> None: ...
    async def feed_audio(self, pcm: bytes) -> None: ...
    async def stop_session(self) -> None: ...
    def set_partial_callback(self, cb: Any) -> None: ...
    def set_event_callback(self, cb: Any) -> None: ...
    def set_interrupt_callback(self, cb: Any) -> None: ...
    def notify_tts_done(self) -> None: ...


def _extract_token(ws: WebSocket) -> str | None:
    auth = ws.headers.get("authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer ") :]

    # Browsers can't set arbitrary headers, so the bearer token piggybacks
    # on the subprotocol list as `bearer.<token>`.
    subprotocols = ws.headers.get("sec-websocket-protocol", "")
    for raw in subprotocols.split(","):
        proto = raw.strip()
        if proto.startswith("bearer."):
            return proto[len("bearer.") :]
    return None


def create_app(
    token: str,
    *,
    turn_loop: TurnLoopLike | None = None,
    voice_pipeline: VoicePipelineLike | None = None,
) -> FastAPI:
    app = FastAPI(title="desktop-ai-agent", version="0.0.0")
    app.state.token = token
    app.state.turn_loop = turn_loop
    app.state.voice_pipeline = voice_pipeline
    # Active WS connections for broadcast (proactive notifications).
    app.state.clients: set[WebSocket] = set()  # type: ignore[misc]

    async def broadcast(msg: dict[str, Any]) -> None:
        """Send a JSON message to all connected WS clients."""
        dead: set[WebSocket] = set()
        clients: set[WebSocket] = app.state.clients
        for ws_client in clients:
            try:
                await ws_client.send_json(msg)
            except Exception:
                dead.add(ws_client)
        clients -= dead

    app.state.broadcast = broadcast

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        got = _extract_token(websocket)
        if got != token:
            await websocket.close(code=4401)
            return

        # Accept with the matching subprotocol if the client sent one.
        subprotocol = None
        proto_header = websocket.headers.get("sec-websocket-protocol", "")
        for raw in proto_header.split(","):
            proto = raw.strip()
            if proto == f"bearer.{token}":
                subprotocol = proto
                break
        await websocket.accept(subprotocol=subprotocol)
        app.state.clients.add(websocket)

        try:
            while True:
                # Mixed-frame handling: text frames carry JSON-RPC,
                # binary frames carry tagged audio (mic = 0x01).
                msg = await websocket.receive()
                if msg.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect
                if "text" in msg and msg["text"] is not None:
                    import json as _json

                    try:
                        envelope = _json.loads(msg["text"])
                    except _json.JSONDecodeError:
                        continue
                    await _dispatch(websocket, envelope, turn_loop, voice_pipeline)
                elif "bytes" in msg and msg["bytes"] is not None:
                    await _handle_binary(msg["bytes"], voice_pipeline)
        except WebSocketDisconnect:
            app.state.clients.discard(websocket)

    return app


async def _handle_binary(
    payload: bytes,
    voice_pipeline: VoicePipelineLike | None,
) -> None:
    """Route a binary frame. Frame layout: tag (1B) + seq (8B LE u64) + payload."""
    if voice_pipeline is None or len(payload) < 9:
        return
    tag = payload[0]
    if tag == 0x01:  # mic PCM
        await voice_pipeline.feed_audio(payload[9:])


async def _dispatch(
    ws: WebSocket,
    msg: dict[str, Any],
    turn_loop: TurnLoopLike | None,
    voice_pipeline: VoicePipelineLike | None,
) -> None:
    method = msg.get("method")
    params = msg.get("params") or {}
    req_id = msg.get("id")

    if method == "session.send_text":
        text = str(params.get("text", ""))
        if turn_loop is None:
            # Phase 0 fallback for tests and bare-bones smoke checks.
            await _send_say(ws, f"echo: {text}", is_thinking=False)
            await _send_event(ws, "agent.say_end", {"message_id": "stub"})
        else:
            await _stream_turn_events(ws, turn_loop.run(text))
        if req_id is not None:
            await ws.send_json({"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}})
        return

    if method == "voice.start":
        if voice_pipeline is None:
            await _send_method_error(ws, req_id, "voice pipeline not configured")
            return

        async def _on_partial(text: str) -> None:
            await _send_event(ws, "voice.stt_partial", {"text": text})

        # Voice mode is continuous: Deepgram's UtteranceEnd fires turns
        # automatically, and SpeechStarted (barge-in) cancels them. Each
        # turn's events flow through this callback in the same wire
        # format the text path uses.
        tts_seq = [0]

        async def _on_event(evt: Any) -> None:
            await _emit_turn_event(ws, evt, tts_seq)

        async def _on_interrupt() -> None:
            # Reset the per-turn TTS seq so the next chunk is treated as
            # the start of a new turn by the frontend's playback queue.
            tts_seq[0] = 0
            await _send_event(ws, "agent.interrupt", {})

        voice_pipeline.set_partial_callback(_on_partial)
        voice_pipeline.set_event_callback(_on_event)
        voice_pipeline.set_interrupt_callback(_on_interrupt)
        await voice_pipeline.start_session()
        if req_id is not None:
            await ws.send_json({"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}})
        return

    if method == "voice.stop":
        if voice_pipeline is None:
            await _send_method_error(ws, req_id, "voice pipeline not configured")
            return
        await voice_pipeline.stop_session()
        voice_pipeline.set_partial_callback(None)
        voice_pipeline.set_event_callback(None)
        voice_pipeline.set_interrupt_callback(None)
        if req_id is not None:
            await ws.send_json({"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}})
        return

    if method == "voice.tts_done":
        # Half-duplex release: client tells us its TTS playback queue
        # has drained, so it's safe to start listening to the user
        # again without catching the tail of our own audio.
        if voice_pipeline is not None:
            voice_pipeline.notify_tts_done()
        if req_id is not None:
            await ws.send_json({"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}})
        return

    if req_id is not None:
        await ws.send_json(
            {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            }
        )


async def _stream_turn_events(
    ws: WebSocket,
    events: AsyncIterator[Any],
) -> None:
    """Pump TurnEvents from a sync turn (session.send_text) to the WS.
    Voice-mode auto-fired turns reuse `_emit_turn_event` directly via the
    pipeline's event callback, so the wire format stays identical."""
    tts_seq_counter = [0]
    async for evt in events:
        await _emit_turn_event(ws, evt, tts_seq_counter)


async def _emit_turn_event(
    ws: WebSocket, evt: Any, tts_seq_counter: list[int]
) -> None:
    if evt.kind == "delta":
        await _send_say(ws, evt.text, is_thinking=evt.is_thinking)
    elif evt.kind == "end":
        await _send_event(ws, "agent.say_end", {"message_id": evt.message_id})
    elif evt.kind == "tool_request":
        await _send_event(
            ws,
            "tool.request_confirm",
            {
                "call_id": evt.call_id,
                "tool": evt.tool_name,
                "args": evt.arguments,
                "risk": evt.risk,
                "requires_confirmation": evt.requires_confirmation,
            },
        )
    elif evt.kind == "tool_result":
        await _send_event(
            ws,
            "tool.result",
            {
                "call_id": evt.call_id,
                "ok": evt.ok,
                "summary": evt.summary,
            },
        )
    elif evt.kind == "tts":
        # Binary frame: tag (0x02) + seq (8B BE u64) + WAV.
        seq = tts_seq_counter[0]
        tts_seq_counter[0] += 1
        tag = b"\x02" + seq.to_bytes(8, "big") + evt.audio_wav
        await ws.send_bytes(tag)


async def _send_method_error(
    ws: WebSocket, req_id: object, message: str
) -> None:
    if req_id is None:
        return
    await ws.send_json(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32000, "message": message},
        }
    )


async def _send_say(ws: WebSocket, text: str, *, is_thinking: bool) -> None:
    await _send_event(
        ws,
        "agent.say",
        {
            "text": text,
            "emotion": "think" if is_thinking else "neutral",
            "is_thinking": is_thinking,
            "delta": True,
        },
    )


async def _send_event(ws: WebSocket, method: str, params: dict[str, Any]) -> None:
    await ws.send_json({"jsonrpc": "2.0", "method": method, "params": params})
