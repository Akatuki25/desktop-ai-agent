"""behavior_config — agent persona / tone / proactivity knobs."""

from __future__ import annotations

import time

from agent.memory.db import Database


class BehaviorConfig:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str) -> str | None:
        row = self._db.conn.execute(
            "SELECT value FROM behavior_config WHERE key = ?", (key,)
        ).fetchone()
        return str(row["value"]) if row else None

    def set(self, key: str, value: str) -> None:
        ts = int(time.time() * 1000)
        self._db.conn.execute(
            """
            INSERT INTO behavior_config(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, value, ts),
        )

    def all(self) -> dict[str, str]:
        rows = self._db.conn.execute(
            "SELECT key, value FROM behavior_config ORDER BY key"
        ).fetchall()
        return {str(r["key"]): str(r["value"]) for r in rows}
