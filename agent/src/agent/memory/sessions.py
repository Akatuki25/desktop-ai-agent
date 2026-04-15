"""Session + message repository.

Covers the structural part of docs/spec-detailed.md §3.6 session
lifecycle. Closing a session (setting ended_at / title / summary) is
driven by the orchestrator — this module just records the state.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Literal

from agent.memory.db import Database

SessionKind = Literal["chat", "proactive", "task", "background_fetch"]
MessageRole = Literal["user", "assistant", "system", "tool"]


@dataclass(frozen=True)
class Session:
    id: str
    kind: SessionKind
    started_at: int
    ended_at: int | None
    title: str | None
    summary: str | None


@dataclass(frozen=True)
class Message:
    id: int
    session_id: str
    role: MessageRole
    content: str
    created_at: int


def _now_ms() -> int:
    return int(time.time() * 1000)


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self._db = db

    # ---- sessions ----
    def create(self, kind: SessionKind, *, session_id: str | None = None) -> Session:
        sid = session_id or uuid.uuid4().hex
        ts = _now_ms()
        self._db.conn.execute(
            "INSERT INTO sessions(id, kind, started_at) VALUES (?, ?, ?)",
            (sid, kind, ts),
        )
        return Session(id=sid, kind=kind, started_at=ts, ended_at=None, title=None, summary=None)

    def get(self, session_id: str) -> Session | None:
        row = self._db.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return _row_to_session(row) if row else None

    def close(self, session_id: str, *, title: str, summary: str) -> None:
        ts = _now_ms()
        self._db.conn.execute(
            """
            UPDATE sessions
               SET ended_at = ?, title = ?, summary = ?
             WHERE id = ?
            """,
            (ts, title, summary, session_id),
        )
        # Keep sessions_fts in sync (no content-table trick because we want
        # both title and summary searchable and they can change over time).
        self._db.conn.execute(
            "DELETE FROM sessions_fts WHERE session_id = ?", (session_id,)
        )
        self._db.conn.execute(
            "INSERT INTO sessions_fts(title, summary, session_id) VALUES (?, ?, ?)",
            (title, summary, session_id),
        )

    def latest_summaries(self, limit: int) -> list[Session]:
        # rowid tiebreaker keeps ordering stable when multiple closes
        # land in the same millisecond (clock resolution on Windows).
        rows = self._db.conn.execute(
            """
            SELECT * FROM sessions
             WHERE summary IS NOT NULL
             ORDER BY COALESCE(ended_at, started_at) DESC, rowid DESC
             LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [_row_to_session(r) for r in rows]

    def open_chat(self) -> Session | None:
        row = self._db.conn.execute(
            """
            SELECT * FROM sessions
             WHERE kind = 'chat' AND ended_at IS NULL
             ORDER BY started_at DESC
             LIMIT 1
            """
        ).fetchone()
        return _row_to_session(row) if row else None

    # ---- messages ----
    def append_message(self, session_id: str, role: MessageRole, content: str) -> Message:
        ts = _now_ms()
        cur = self._db.conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (session_id, role, content, ts),
        )
        mid = int(cur.lastrowid or 0)
        return Message(id=mid, session_id=session_id, role=role, content=content, created_at=ts)

    def recent_messages(self, session_id: str, limit: int) -> list[Message]:
        rows = self._db.conn.execute(
            """
            SELECT * FROM messages
             WHERE session_id = ?
             ORDER BY id DESC
             LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [_row_to_message(r) for r in reversed(rows)]


def _row_to_session(row: sqlite3.Row) -> Session:
    ended_at = row["ended_at"]
    return Session(
        id=str(row["id"]),
        kind=str(row["kind"]),  # type: ignore[arg-type]
        started_at=int(row["started_at"]),
        ended_at=int(ended_at) if ended_at is not None else None,
        title=str(row["title"]) if row["title"] is not None else None,
        summary=str(row["summary"]) if row["summary"] is not None else None,
    )


def _row_to_message(row: sqlite3.Row) -> Message:
    return Message(
        id=int(row["id"]),
        session_id=str(row["session_id"]),
        role=str(row["role"]),  # type: ignore[arg-type]
        content=str(row["content"]),
        created_at=int(row["created_at"]),
    )
