"""schedule.register_task tool — let the LLM register cron tasks."""

from __future__ import annotations

from typing import Any

from agent.scheduler.cron import CronScheduler
from agent.tools.base import Tool


class ScheduleRegisterTool(Tool):
    name = "schedule.register_task"
    description = (
        "Register a new scheduled task. The cron field uses standard "
        "5-field crontab syntax (minute hour day month weekday). The "
        "prompt field is what the agent will say when the task fires."
    )
    risk = "medium"
    requires_confirmation = True

    def __init__(self, scheduler: CronScheduler) -> None:
        self._scheduler = scheduler

    def parameters_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["cron", "prompt"],
            "properties": {
                "cron": {
                    "type": "string",
                    "description": "Crontab expression (5 fields)",
                },
                "prompt": {
                    "type": "string",
                    "description": "What the agent should say when this fires",
                },
            },
        }

    async def execute(self, args: dict[str, Any]) -> Any:
        cron = str(args["cron"])
        prompt = str(args["prompt"])
        task_id = self._scheduler.add_task(cron, prompt)
        return {"ok": True, "task_id": task_id, "cron": cron}
