"""Tests for SessionCloseTool and SessionManager.run_idle_watcher."""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest

from agent.llm import FakeLLMBackend
from agent.memory import Database, SessionRepository
from agent.orchestrator import SessionManager
from agent.tools.session_tools import SessionCloseTool


@pytest.fixture()
def repo(tmp_path: Path) -> SessionRepository:
    return SessionRepository(Database(tmp_path / "s.sqlite"))


@pytest.mark.asyncio
async def test_session_close_tool_summarizes_open_chat(
    repo: SessionRepository,
) -> None:
    llm = FakeLLMBackend('{"title":"farewell","summary":"chat ended"}')
    sm = SessionManager(repo, llm)
    s = repo.create("chat")
    repo.append_message(s.id, "user", "hi")
    repo.append_message(s.id, "assistant", "hello")

    tool = SessionCloseTool(sm)
    result = await tool.execute({})

    assert result == {"ok": True}
    closed = repo.get(s.id)
    assert closed is not None
    assert closed.ended_at is not None
    assert closed.title == "farewell"
    assert closed.summary == "chat ended"


@pytest.mark.asyncio
async def test_session_close_tool_is_noop_when_no_open_chat(
    repo: SessionRepository,
) -> None:
    llm = FakeLLMBackend("unused")
    sm = SessionManager(repo, llm)

    # No session created — close_current should silently no-op.
    result = await SessionCloseTool(sm).execute({})
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_idle_watcher_closes_idle_chat(
    repo: SessionRepository,
) -> None:
    llm = FakeLLMBackend('{"title":"auto","summary":"timed out"}')
    sm = SessionManager(repo, llm, idle_timeout_s=0.05)
    s = repo.create("chat")
    repo.append_message(s.id, "user", "hi")

    # Run the watcher with a tight cadence; let it fire once.
    task = asyncio.create_task(sm.run_idle_watcher(interval_s=0.02))
    # Wait long enough for at least one poll past the idle threshold.
    await asyncio.sleep(0.2)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    closed = repo.get(s.id)
    assert closed is not None
    assert closed.ended_at is not None
    assert closed.title == "auto"


@pytest.mark.asyncio
async def test_idle_watcher_skips_active_chat(
    repo: SessionRepository,
) -> None:
    llm = FakeLLMBackend("should-not-be-called")
    sm = SessionManager(repo, llm, idle_timeout_s=10.0)
    s = repo.create("chat")
    sm.touch(s.id)

    task = asyncio.create_task(sm.run_idle_watcher(interval_s=0.02))
    await asyncio.sleep(0.1)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    # Still open — idle threshold (10s) hasn't been crossed.
    still_open = repo.open_chat()
    assert still_open is not None
    assert still_open.id == s.id
    assert still_open.ended_at is None


@pytest.mark.asyncio
async def test_idle_watcher_cancels_cleanly_during_sleep(
    repo: SessionRepository,
) -> None:
    """Cancelling while the watcher is in `await asyncio.sleep` must exit
    without raising — the shutdown hook depends on this."""
    llm = FakeLLMBackend("unused")
    sm = SessionManager(repo, llm)

    task = asyncio.create_task(sm.run_idle_watcher(interval_s=10.0))
    await asyncio.sleep(0.05)
    task.cancel()
    # Should complete (not raise) because the watcher swallows CancelledError.
    await task
