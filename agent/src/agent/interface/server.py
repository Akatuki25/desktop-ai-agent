"""FastAPI + WebSocket server wired to the orchestrator.

Phase 0+: session.send_text hands the text to the TurnLoop and streams
each SayEvent back as an `agent.say` JSON-RPC notification, finishing
with `agent.say_end`. If the app is built without an orchestrator
(e.g. unit tests that only care about the WS contract) the server
falls back to the Phase 0 echo behaviour so existing smoke tests
don't regress.

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


def create_app(token: str, *, turn_loop: TurnLoopLike | None = None) -> FastAPI:
    app = FastAPI(title="desktop-ai-agent", version="0.0.0")
    app.state.token = token
    app.state.turn_loop = turn_loop
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
                msg: dict[str, Any] = await websocket.receive_json()
                await _dispatch(websocket, msg, turn_loop)
        except WebSocketDisconnect:
            app.state.clients.discard(websocket)

    return app


async def _dispatch(
    ws: WebSocket,
    msg: dict[str, Any],
    turn_loop: TurnLoopLike | None,
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
            async for evt in turn_loop.run(text):
                if evt.kind == "delta":
                    await _send_say(ws, evt.text, is_thinking=evt.is_thinking)
                elif evt.kind == "end":
                    await _send_event(
                        ws, "agent.say_end", {"message_id": evt.message_id}
                    )
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
                    # Send TTS audio as a binary WS frame.
                    # Tag byte 0x02 = tts, then 8 bytes seq (0 for now),
                    # then WAV payload.
                    tag = b"\x02" + b"\x00" * 8 + evt.audio_wav
                    await ws.send_bytes(tag)

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
