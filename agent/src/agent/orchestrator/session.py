"""SessionManager — lifecycle for chat sessions.

Handles:
- current_or_new_chat: reuse an open session or create a fresh one
- idle timeout: mark a session stale after N seconds of no user activity
- close + summarize: on close, ask the LLM for a title and summary
  and persist them so they become part of the next session's hot context
"""

from __future__ import annotations

import asyncio
import sys
import time

from agent.llm.backend import LLMBackend, Message
from agent.memory import Session, SessionRepository

_IDLE_TIMEOUT_S = 600  # 10 minutes per spec §3.6
_IDLE_WATCHER_INTERVAL_S = 60.0  # poll cadence; cheap because it's just a SELECT


class SessionManager:
    def __init__(
        self,
        repo: SessionRepository,
        llm: LLMBackend,
        *,
        idle_timeout_s: float = _IDLE_TIMEOUT_S,
    ) -> None:
        self._repo = repo
        self._llm = llm
        self._idle_timeout_s = idle_timeout_s
        self._last_activity: dict[str, float] = {}

    def current_or_new_chat(self) -> Session:
        existing = self._repo.open_chat()
        if existing is not None:
            # Check idle timeout
            last = self._last_activity.get(existing.id, existing.started_at / 1000)
            if time.time() - last > self._idle_timeout_s:
                asyncio.get_event_loop().create_task(
                    self._close_and_summarize(existing.id)
                )
                return self._repo.create("chat")
            return existing
        return self._repo.create("chat")

    def touch(self, session_id: str) -> None:
        """Record user activity so idle timeout resets."""
        self._last_activity[session_id] = time.time()

    async def close_current(self) -> None:
        """Force-close the current chat session (e.g. on app exit)."""
        s = self._repo.open_chat()
        if s is not None:
            await self._close_and_summarize(s.id)

    async def run_idle_watcher(
        self, *, interval_s: float = _IDLE_WATCHER_INTERVAL_S
    ) -> None:
        """Background polling loop: closes the open chat once it goes idle.

        The synchronous `current_or_new_chat` path only fires a close on the
        next user turn, which means a user who walks away never gets their
        session summarized. This watcher fills that gap by polling every
        `interval_s` and closing anything past `_idle_timeout_s`.

        Returns when cancelled. Summarize errors are caught and logged so
        a single bad turn can't kill the watcher.
        """
        while True:
            try:
                await asyncio.sleep(interval_s)
            except asyncio.CancelledError:
                break
            try:
                existing = self._repo.open_chat()
                if existing is None:
                    continue
                last = self._last_activity.get(
                    existing.id, existing.started_at / 1000
                )
                if time.time() - last > self._idle_timeout_s:
                    await self._close_and_summarize(existing.id)
            except Exception as e:
                sys.stderr.write(f"[session] idle watcher error: {e}\n")

    async def _close_and_summarize(self, session_id: str) -> None:
        messages = self._repo.recent_messages(session_id, limit=50)
        if not messages:
            self._repo.close(session_id, title="(empty)", summary="")
            return

        history_text = "\n".join(f"{m.role}: {m.content}" for m in messages)
        prompt = [
            Message(
                role="system",
                content=(
                    "You are a summarizer. Given a conversation, produce a JSON object "
                    'with two keys: "title" (short, max 30 chars) and "summary" '
                    "(2-3 sentences capturing the key points). Respond with ONLY "
                    "the JSON, no other text. Use the same language as the conversation."
                ),
            ),
            Message(role="user", content=history_text),
        ]

        result_parts: list[str] = []
        async for chunk in self._llm.chat_stream(prompt, thinking=False):
            if chunk.done:
                break
            if not chunk.is_thinking:
                result_parts.append(chunk.text)

        raw = "".join(result_parts).strip()
        title, summary = _parse_summary(raw)
        self._repo.close(session_id, title=title, summary=summary)
        self._last_activity.pop(session_id, None)


def _parse_summary(raw: str) -> tuple[str, str]:
    """Best-effort parse of LLM summary JSON. Falls back gracefully."""
    import json

    try:
        obj = json.loads(raw)
        return str(obj.get("title", ""))[:80], str(obj.get("summary", ""))
    except (json.JSONDecodeError, AttributeError):
        # LLM didn't return valid JSON — use the raw text as summary
        lines = raw.strip().splitlines()
        title = lines[0][:80] if lines else "(untitled)"
        return title, raw[:500]
