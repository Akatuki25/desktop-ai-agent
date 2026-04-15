"""Integration test: WS server + orchestrator + FakeLLMBackend.

Ensures the full pipe from session.send_text → orchestrator →
FakeLLMBackend → streamed agent.say events works end-to-end and that
messages are persisted.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agent.interface.server import create_app
from agent.llm import FakeLLMBackend
from agent.memory import BehaviorConfig, CoreMemory, Database, SessionRepository
from agent.orchestrator import SessionManager, TurnLoop


@pytest.fixture()
def app_with_orchestrator(tmp_path: Path) -> tuple[TestClient, SessionRepository]:
    db = Database(tmp_path / "ws.sqlite")
    repo = SessionRepository(db)
    core = CoreMemory(db)
    behavior = BehaviorConfig(db)
    llm = FakeLLMBackend("<think>plan</think>こんにちは akatuki", chunk_size=5)
    loop = TurnLoop(
        sessions=repo,
        session_manager=SessionManager(repo),
        core_memory=core,
        behavior=behavior,
        llm=llm,
    )
    app = create_app(token="tok", turn_loop=loop)
    return TestClient(app), repo


def test_ws_streams_orchestrator_output(
    app_with_orchestrator: tuple[TestClient, SessionRepository],
) -> None:
    client, repo = app_with_orchestrator
    with client.websocket_connect(
        "/ws", headers={"authorization": "Bearer tok"}
    ) as ws:
        ws.send_json(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "session.send_text",
                "params": {"text": "やあ"},
            }
        )

        main: list[str] = []
        thinking: list[str] = []
        end_seen = False
        ack_seen = False

        while not (end_seen and ack_seen):
            frame = ws.receive_json()
            if "method" in frame:
                if frame["method"] == "agent.say":
                    if frame["params"]["is_thinking"]:
                        thinking.append(frame["params"]["text"])
                    else:
                        main.append(frame["params"]["text"])
                elif frame["method"] == "agent.say_end":
                    end_seen = True
            elif frame.get("id") == 1:
                assert frame["result"] == {"ok": True}
                ack_seen = True

    assert "".join(main).strip() == "こんにちは akatuki"
    assert "".join(thinking) == "plan"

    session = repo.open_chat()
    assert session is not None
    history = repo.recent_messages(session.id, 10)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "やあ"
    assert history[1].content == "こんにちは akatuki"


def test_subprotocol_bearer_auth_works(
    app_with_orchestrator: tuple[TestClient, SessionRepository],
) -> None:
    client, _ = app_with_orchestrator
    # Starlette's TestClient sends the subprotocols list correctly.
    with client.websocket_connect("/ws", subprotocols=["bearer.tok"]) as ws:
        ws.send_json(
            {"jsonrpc": "2.0", "method": "session.send_text", "params": {"text": "x"}}
        )
        # Just drain until we see agent.say_end — we already covered content above.
        while True:
            frame = ws.receive_json()
            if frame.get("method") == "agent.say_end":
                break
