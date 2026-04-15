"""Round-trip + FTS5 coverage for the memory layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.memory import (
    BehaviorConfig,
    CoreMemory,
    Database,
    MemorySearch,
    SessionRepository,
)


@pytest.fixture()
def db(tmp_path: Path) -> Database:
    return Database(tmp_path / "test.sqlite")


def test_core_memory_roundtrip(db: Database) -> None:
    cm = CoreMemory(db)
    cm.set("persona", "helpful desktop agent")
    cm.set("user_name", "akatuki")
    assert cm.get("persona") == "helpful desktop agent"
    assert cm.all() == {"persona": "helpful desktop agent", "user_name": "akatuki"}

    cm.set("persona", "even more helpful")
    assert cm.get("persona") == "even more helpful"

    cm.delete("user_name")
    assert cm.get("user_name") is None


def test_behavior_config_roundtrip(db: Database) -> None:
    bc = BehaviorConfig(db)
    bc.set("tone", "friendly")
    bc.set("proactivity", "2")
    assert bc.all() == {"tone": "friendly", "proactivity": "2"}


def test_session_lifecycle(db: Database) -> None:
    repo = SessionRepository(db)
    s = repo.create("chat")
    assert s.kind == "chat"
    assert s.ended_at is None
    assert repo.open_chat() is not None

    m1 = repo.append_message(s.id, "user", "hello")
    m2 = repo.append_message(s.id, "assistant", "hi there")
    assert m1.id < m2.id
    assert [m.content for m in repo.recent_messages(s.id, 10)] == ["hello", "hi there"]

    repo.close(s.id, title="greeting", summary="user said hello, assistant replied")
    closed = repo.get(s.id)
    assert closed is not None
    assert closed.ended_at is not None
    assert closed.summary == "user said hello, assistant replied"
    assert repo.open_chat() is None


def test_latest_summaries_excludes_open_sessions(db: Database) -> None:
    repo = SessionRepository(db)
    a = repo.create("chat")
    repo.close(a.id, title="a", summary="summary A")
    b = repo.create("chat")
    repo.close(b.id, title="b", summary="summary B")
    # open chat should not appear
    repo.create("chat")

    latest = repo.latest_summaries(limit=5)
    assert [s.summary for s in latest] == ["summary B", "summary A"]


def test_fts5_finds_message_by_keyword(db: Database) -> None:
    repo = SessionRepository(db)
    search = MemorySearch(db)
    s = repo.create("chat")
    repo.append_message(s.id, "user", "Rustのリンカエラーで詰まっている")
    repo.append_message(s.id, "assistant", "link.exeがcoreutilsと衝突しています")
    repo.append_message(s.id, "user", "ありがとう")

    hits = search.search("link.exe")
    assert any("link.exe" in h.snippet.replace("[", "").replace("]", "") for h in hits)
    assert all(h.session_id == s.id for h in hits if h.kind == "message")


def test_fts5_finds_session_by_summary(db: Database) -> None:
    repo = SessionRepository(db)
    search = MemorySearch(db)
    s = repo.create("task")
    repo.close(
        s.id,
        title="build fix",
        summary="resolved Windows linker shadowing by using PowerShell",
    )

    hits = search.search("Windows linker")
    session_hits = [h for h in hits if h.kind == "session"]
    assert session_hits
    assert session_hits[0].session_id == s.id


def test_fts5_empty_query_returns_nothing(db: Database) -> None:
    search = MemorySearch(db)
    assert search.search("") == []
    assert search.search("   ") == []
