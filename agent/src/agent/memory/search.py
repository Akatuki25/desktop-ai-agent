"""memory.search — FTS5 keyword lookup across messages and sessions.

The MATCH target is intentionally trigram-only; callers pass a plain
string and we let sqlite quote it as a single phrase. For grep-like
keyword queries this is the least-surprising behaviour (no syntax
errors on stray Japanese/English punctuation).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from agent.memory.db import Database

SearchKind = Literal["message", "session"]


@dataclass(frozen=True)
class SearchHit:
    kind: SearchKind
    session_id: str
    snippet: str
    score: float


def _escape(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


class MemorySearch:
    def __init__(self, db: Database) -> None:
        self._db = db

    def search(self, query: str, *, limit: int = 10) -> list[SearchHit]:
        if not query.strip():
            return []
        q = _escape(query)

        hits: list[SearchHit] = []

        for row in self._db.conn.execute(
            """
            SELECT session_id,
                   snippet(messages_fts, 0, '[', ']', '...', 16) AS snippet,
                   bm25(messages_fts) AS score
              FROM messages_fts
             WHERE messages_fts MATCH ?
             ORDER BY score
             LIMIT ?
            """,
            (q, limit),
        ).fetchall():
            hits.append(
                SearchHit(
                    kind="message",
                    session_id=str(row["session_id"]),
                    snippet=str(row["snippet"]),
                    score=float(row["score"]),
                )
            )

        for row in self._db.conn.execute(
            """
            SELECT session_id,
                   snippet(sessions_fts, 1, '[', ']', '...', 16) AS snippet,
                   bm25(sessions_fts) AS score
              FROM sessions_fts
             WHERE sessions_fts MATCH ?
             ORDER BY score
             LIMIT ?
            """,
            (q, limit),
        ).fetchall():
            hits.append(
                SearchHit(
                    kind="session",
                    session_id=str(row["session_id"]),
                    snippet=str(row["snippet"]),
                    score=float(row["score"]),
                )
            )

        hits.sort(key=lambda h: h.score)
        return hits[:limit]
