"""FastAPI + WebSocket server for Tauri ↔ daemon communication.

Phase 0 behaviour: accept text via `session.send_text`, echo it back as an
`agent.say` event followed by `agent.say_end`. This exists only so the UI
stack can be wired end-to-end before the real orchestrator lands.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def create_app(token: str) -> FastAPI:
    app = FastAPI(title="desktop-ai-agent", version="0.0.0")
    app.state.token = token

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket) -> None:
        auth = websocket.headers.get("authorization", "")
        if auth != f"Bearer {token}":
            await websocket.close(code=4401)
            return

        await websocket.accept()
        try:
            while True:
                msg: dict[str, Any] = await websocket.receive_json()
                method = msg.get("method")
                params = msg.get("params") or {}
                req_id = msg.get("id")

                if method == "session.send_text":
                    text = str(params.get("text", ""))
                    await websocket.send_json(
                        {
                            "jsonrpc": "2.0",
                            "method": "agent.say",
                            "params": {
                                "text": f"echo: {text}",
                                "emotion": "neutral",
                                "is_thinking": False,
                                "delta": False,
                            },
                        }
                    )
                    await websocket.send_json(
                        {
                            "jsonrpc": "2.0",
                            "method": "agent.say_end",
                            "params": {"message_id": "stub"},
                        }
                    )
                    if req_id is not None:
                        await websocket.send_json(
                            {"jsonrpc": "2.0", "id": req_id, "result": {"ok": True}}
                        )
                elif req_id is not None:
                    await websocket.send_json(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {"code": -32601, "message": f"method not found: {method}"},
                        }
                    )
        except WebSocketDisconnect:
            return

    return app
