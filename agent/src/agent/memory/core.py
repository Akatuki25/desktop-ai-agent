"""core_memory key-value store injected into every system prompt."""

from __future__ import annotations

import time

from agent.memory.db import Database


class CoreMemory:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        row = self._db.conn.execute(
            "SELECT value FROM core_memory WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set(self, key: str, value: str) -> None:
        ts = int(time.time() * 1000)
        self._db.conn.execute(
            """
            INSERT INTO core_memory(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, ts),
        )

    def all(self) -> dict[str, str]:
        rows = self._db.conn.execute("SELECT key, value FROM core_memory ORDER BY key").fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}

    def delete(self, key: str) -> None:
        self._db.conn.execute("DELETE FROM core_memory WHERE key = ?", (key,))
