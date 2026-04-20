"""APScheduler wrapper for cron-driven tasks.

Reads scheduled_tasks from SQLite, registers APScheduler CronTriggers,
and fires a callback when each task is due. The callback creates a
proactive session and asks the LLM to speak.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Coroutine
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]
from apscheduler.triggers.cron import CronTrigger  # type: ignore[import-untyped]

from agent.memory.db import Database

ProactiveCallback = Callable[[str], Coroutine[Any, Any, None]]


class CronScheduler:
    def __init__(self, db: Database, callback: ProactiveCallback) -> None:
        self._db = db
        self._callback = callback
        self._scheduler = AsyncIOScheduler()

    def load_tasks(self) -> int:
        """Read scheduled_tasks from DB and register APScheduler jobs.

        Returns the number of tasks loaded.
        """
        rows = self._db.conn.execute(
            "SELECT id, cron, prompt, enabled FROM scheduled_tasks WHERE enabled = 1"
        ).fetchall()
        for row in rows:
            task_id = str(row["id"])
            cron_expr = str(row["cron"])
            prompt = str(row["prompt"])
            try:
                trigger = CronTrigger.from_crontab(cron_expr)
                self._scheduler.add_job(
                    self._fire,
                    trigger=trigger,
                    args=[prompt],
                    id=f"task_{task_id}",
                    replace_existing=True,
                )
            except Exception as e:
                sys.stderr.write(
                    f"[scheduler] failed to register task {task_id} "
                    f"(cron={cron_expr!r}): {e}\n"
                )
        return len(rows)

    async def _fire(self, prompt: str) -> None:
        await self._callback(prompt)

    def start(self) -> None:
        n = self.load_tasks()
        sys.stderr.write(f"[scheduler] started with {n} task(s)\n")
        self._scheduler.start()

    def stop(self) -> None:
        self._scheduler.shutdown(wait=False)

    def add_task(self, cron: str, prompt: str) -> int:
        """Insert a new scheduled task and register it immediately."""
        cur = self._db.conn.execute(
            "INSERT INTO scheduled_tasks(cron, prompt, enabled) VALUES (?, ?, 1)",
            (cron, prompt),
        )
        task_id = int(cur.lastrowid or 0)
        trigger = CronTrigger.from_crontab(cron)
        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            args=[prompt],
            id=f"task_{task_id}",
            replace_existing=True,
        )
        return task_id
