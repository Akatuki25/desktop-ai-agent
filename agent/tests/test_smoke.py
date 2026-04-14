"""Phase 0 smoke tests: server imports, healthz, WS auth, WS echo."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agent.interface.server import create_app


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(token="test"))


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_ws_requires_bearer_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws"):
            pass


def test_ws_rejects_wrong_token(client: TestClient) -> None:
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws", headers={"authorization": "Bearer wrong"}):
            pass


def test_ws_echoes_send_text(client: TestClient) -> None:
    with client.websocket_connect(
        "/ws", headers={"authorization": "Bearer test"}
    ) as ws:
        ws.send_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session.send_text",
                "params": {"text": "hello"},
            }
        )
        say = ws.receive_json()
        assert say["method"] == "agent.say"
        assert say["params"]["text"] == "echo: hello"
        assert say["params"]["emotion"] == "neutral"

        end = ws.receive_json()
        assert end["method"] == "agent.say_end"

        ack = ws.receive_json()
        assert ack["id"] == 1
        assert ack["result"] == {"ok": True}


def test_ws_unknown_method_returns_error(client: TestClient) -> None:
    with client.websocket_connect(
        "/ws", headers={"authorization": "Bearer test"}
    ) as ws:
        ws.send_json({"jsonrpc": "2.0", "id": 2, "method": "nope"})
        resp = ws.receive_json()
        assert resp["id"] == 2
        assert resp["error"]["code"] == -32601
