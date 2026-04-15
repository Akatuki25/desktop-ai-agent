"""SessionManager — creates / reuses / closes chat sessions.

Only the chat kind is implemented here for Phase 0. proactive, task and
background_fetch sessions plus idle-timeout sweeping land with the
scheduler in Phase 2.
"""

from __future__ import annotations

from agent.memory import Session, SessionRepository


class SessionManager:
    def __init__(self, repo: SessionRepository) -> None:
        self._repo = repo

    def current_or_new_chat(self) -> Session:
        existing = self._repo.open_chat()
        if existing is not None:
            return existing
        return self._repo.create("chat")

    def close(self, session_id: str, *, title: str, summary: str) -> None:
        self._repo.close(session_id, title=title, summary=summary)
