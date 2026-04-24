"""Build the LLM message list from hot context + session history.

Spec: docs/spec-detailed.md §3.5 — hot context is
core_memory + behavior_config + the N most recent session summaries,
rendered into a single system message. Cold lookup (memory.search) is
a future tool call, not a prompt injection.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent.llm.backend import Message
from agent.memory import BehaviorConfig, CoreMemory, SessionRepository
from agent.memory import Message as StoredMessage

_JST = timezone(offset=__import__("datetime").timedelta(hours=9))


def build_system_prompt(
    core: CoreMemory,
    behavior: BehaviorConfig,
    repo: SessionRepository,
    *,
    recent_summaries: int = 10,
) -> str:
    now = datetime.now(_JST)
    parts: list[str] = [
        "You are a desktop companion agent. Speak concisely in the user's language.",
        "When you think step by step, wrap reasoning in <think>...</think>;"
        " everything outside those tags is shown directly to the user.",
        f"## Current date and time\n{now.strftime('%Y-%m-%d %H:%M:%S')} JST"
        f" ({now.strftime('%A')})",
        "When the user asks to schedule something using relative time"
        ' (e.g. "5分後", "30分後"), calculate the absolute time from'
        " the current time above, then convert it to a cron expression."
        " For one-shot tasks, use the exact minute/hour/day fields.",
        "## CRITICAL: Tool usage rules\n"
        "- You MUST actually call tools using the tool_call mechanism."
        " NEVER pretend you called a tool by writing about it in text.\n"
        "- If you need to search memory, CALL memory.search — do not"
        " fabricate results.\n"
        "- If you need to register a schedule, CALL schedule.register_task"
        " — do not just say you did it.\n"
        "- If a tool call fails, tell the user honestly.\n"
        "- NEVER claim you performed an action that you did not actually"
        " execute through a tool call.",
    ]

    core_items = core.all()
    if core_items:
        rendered = "\n".join(f"- {k}: {v}" for k, v in core_items.items())
        parts.append(f"## User profile / core memory\n{rendered}")

    behavior_items = behavior.all()
    if behavior_items:
        rendered = "\n".join(f"- {k}: {v}" for k, v in behavior_items.items())
        parts.append(f"## Behavior configuration\n{rendered}")

    summaries = repo.latest_summaries(limit=recent_summaries)
    if summaries:
        lines = []
        for s in summaries:
            title = s.title or "(untitled)"
            summary = s.summary or ""
            lines.append(f"- [{title}] {summary}")
        parts.append("## Recent session summaries (most recent first)\n" + "\n".join(lines))

    return "\n\n".join(parts)


def build_messages(
    system_prompt: str,
    history: list[StoredMessage],
) -> list[Message]:
    msgs: list[Message] = [Message(role="system", content=system_prompt)]
    for m in history:
        if m.role in ("user", "assistant", "system", "tool"):
            msgs.append(Message(role=m.role, content=m.content))
    return msgs
