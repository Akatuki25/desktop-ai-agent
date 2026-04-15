"""Orchestrator tests — FakeLLMBackend drives the turn loop end-to-end."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.llm import FakeLLMBackend
from agent.memory import BehaviorConfig, CoreMemory, Database, SessionRepository
from agent.orchestrator import SessionManager, TurnLoop, build_messages
from agent.orchestrator.prompt import build_system_prompt


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "o.sqlite")


@pytest.fixture()
def pieces(db: Database) -> tuple[SessionRepository, CoreMemory, BehaviorConfig]:
    return SessionRepository(db), CoreMemory(db), BehaviorConfig(db)


def test_build_system_prompt_includes_hot_context(
    pieces: tuple[SessionRepository, CoreMemory, BehaviorConfig],
) -> None:
    repo, core, behavior = pieces
    core.set("user_name", "akatuki")
    behavior.set("tone", "concise")
    s = repo.create("chat")
    repo.close(s.id, title="prior chat", summary="talked about Tauri setup")

    prompt = build_system_prompt(core, behavior, repo)
    assert "user_name: akatuki" in prompt
    assert "tone: concise" in prompt
    assert "talked about Tauri setup" in prompt


def test_build_messages_keeps_roles_and_order(
    pieces: tuple[SessionRepository, CoreMemory, BehaviorConfig],
) -> None:
    repo, _, _ = pieces
    s = repo.create("chat")
    repo.append_message(s.id, "user", "hi")
    repo.append_message(s.id, "assistant", "hello")
    history = repo.recent_messages(s.id, 10)

    msgs = build_messages("SYSTEM", history)
    assert [m.role for m in msgs] == ["system", "user", "assistant"]
    assert msgs[0].content == "SYSTEM"
    assert msgs[1].content == "hi"
    assert msgs[2].content == "hello"


@pytest.mark.asyncio
async def test_turn_loop_persists_and_streams(
    db: Database,
    pieces: tuple[SessionRepository, CoreMemory, BehaviorConfig],
) -> None:
    repo, core, behavior = pieces
    llm = FakeLLMBackend("<think>plan</think>こんにちは", chunk_size=4)
    loop = TurnLoop(
        sessions=repo,
        session_manager=SessionManager(repo),
        core_memory=core,
        behavior=behavior,
        llm=llm,
    )

    main: list[str] = []
    thinking: list[str] = []
    end_seen = False
    async for evt in loop.run("よろしく"):
        if evt.kind == "end":
            end_seen = True
        elif evt.is_thinking:
            thinking.append(evt.text)
        else:
            main.append(evt.text)

    assert end_seen
    assert "".join(main) == "こんにちは"
    assert "".join(thinking) == "plan"

    # Session should be open and contain both user and assistant messages.
    session = repo.open_chat()
    assert session is not None
    history = repo.recent_messages(session.id, 10)
    assert [m.role for m in history] == ["user", "assistant"]
    assert history[0].content == "よろしく"
    assert history[1].content == "こんにちは"


@pytest.mark.asyncio
async def test_turn_loop_reuses_existing_session(
    db: Database,
    pieces: tuple[SessionRepository, CoreMemory, BehaviorConfig],
) -> None:
    repo, core, behavior = pieces
    llm = FakeLLMBackend("ok")
    loop = TurnLoop(
        sessions=repo,
        session_manager=SessionManager(repo),
        core_memory=core,
        behavior=behavior,
        llm=llm,
    )

    async for _ in loop.run("first"):
        pass
    first_session = repo.open_chat()
    assert first_session is not None

    async for _ in loop.run("second"):
        pass
    second_session = repo.open_chat()
    assert second_session is not None
    assert first_session.id == second_session.id
    history = repo.recent_messages(second_session.id, 10)
    assert [m.content for m in history] == ["first", "ok", "second", "ok"]
