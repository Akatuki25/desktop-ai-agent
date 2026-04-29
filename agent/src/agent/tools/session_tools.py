"""session.close tool — explicit save-and-summarize for the current chat."""

from __future__ import annotations

from typing import Any

from agent.orchestrator.session import SessionManager
from agent.tools.base import Tool


class SessionCloseTool(Tool):
    name = "session.close"
    description = (
        "現在の会話セッションを締め、LLM が生成する title と要約を memory として保存する。"
        "ユーザが「ここで一区切り」「保存して」「会話を閉じて」など明示的に指示した時のみ呼ぶ。"
        "通常の応答中には使わない (アイドル時は別の watcher が自動で閉じる)。"
    )
    risk = "low"
    requires_confirmation = False

    def __init__(self, session_manager: SessionManager) -> None:
        self._sm = session_manager

    def parameters_schema(self) -> dict[str, Any]:
        return {"type": "object", "properties": {}}

    async def execute(self, args: dict[str, Any]) -> Any:
        await self._sm.close_current()
        return {"ok": True}
