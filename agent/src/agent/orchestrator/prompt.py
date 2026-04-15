"""Build the LLM message list from hot context + session history.

Spec: docs/spec-detailed.md §3.5 — hot context is
core_memory + behavior_config + the N most recent session summaries,
rendered into a single system message. Cold lookup (memory.search) is
a future tool call, not a prompt injection.
"""

from __future__ import annotations

from agent.llm.backend import Message
from agent.memory import BehaviorConfig, CoreMemory, SessionRepository
from agent.memory import Message as StoredMessage


def build_system_prompt(
    core: CoreMemory,
    behavior: BehaviorConfig,
    repo: SessionRepository,
    *,
    recent_summaries: int = 10,
) -> str:
    parts: list[str] = [
        "You are a desktop companion agent. Speak concisely in the user's language.",
        "When you think step by step, wrap reasoning in <think>...</think>;"
        " everything outside those tags is shown directly to the user.",
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
        if m.role in ("user", "assistant", "system"):
            msgs.append(Message(role=m.role, content=m.content))
    return msgs
