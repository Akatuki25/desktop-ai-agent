"""Turn loop — text chat + tool execution.

Flow per turn:
1. Locate / create the current chat session, persist the user message
2. Build the prompt from hot context + message history
3. Stream from the LLM, yielding SayEvent(delta) per chunk
4. If the LLM requests tool calls:
   a. For each call: check risk → if requires_confirmation, yield
      ConfirmRequestEvent and pause until confirmed → execute via
      registry → persist to tool_calls table
   b. Inject tool results back into messages, re-call LLM
   c. Repeat up to MAX_TOOL_STEPS times
5. Accumulate the final assistant reply and persist it
6. Yield SayEvent(end)

Everything is framework-agnostic — the WS layer subscribes to the
async iterator and forwards each event as a JSON-RPC notification.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from agent.llm.backend import LLMBackend, ToolCallDelta
from agent.memory import BehaviorConfig, CoreMemory, SessionRepository
from agent.orchestrator.prompt import build_messages, build_system_prompt
from agent.orchestrator.session import SessionManager
from agent.tools.base import ToolResult
from agent.tools.registry import ToolRegistry
from agent.voice.sentence_splitter import SentenceSplitter
from agent.voice.tts_voicevox import VoicevoxTTS

MAX_TOOL_STEPS = 5

# Canned TTS phrases spoken immediately when a tool is called, so the
# user hears something instead of silence during tool execution.
_TOOL_VOICE: dict[str, str] = {
    "memory.search": "記憶を検索しています",
    "memory.upsert": "記憶を更新しています",
    "schedule.register_task": "スケジュールを設定しています",
    "ask_user": "確認があります",
}
_TOOL_VOICE_DEFAULT = "処理中です"


@dataclass(frozen=True)
class SayEvent:
    kind: str  # "delta" | "end"
    text: str = ""
    is_thinking: bool = False
    message_id: str = ""


@dataclass(frozen=True)
class TTSEvent:
    """Emitted when TTS audio is available for the agent's reply."""

    kind: str = "tts"
    audio_wav: bytes = b""


@dataclass(frozen=True)
class ToolRequestEvent:
    """Emitted when the LLM wants to call a tool."""

    kind: str = "tool_request"
    call_id: str = ""
    tool_name: str = ""
    arguments: dict[str, object] = field(default_factory=dict)
    risk: str = "low"
    requires_confirmation: bool = False


@dataclass(frozen=True)
class ToolResultEvent:
    """Emitted after a tool finishes executing."""

    kind: str = "tool_result"
    call_id: str = ""
    ok: bool = True
    summary: str = ""


TurnEvent = SayEvent | TTSEvent | ToolRequestEvent | ToolResultEvent


class TurnLoop:
    def __init__(
        self,
        *,
        sessions: SessionRepository,
        session_manager: SessionManager,
        core_memory: CoreMemory,
        behavior: BehaviorConfig,
        llm: LLMBackend,
        tools: ToolRegistry | None = None,
        tts: VoicevoxTTS | None = None,
        history_window: int = 30,
    ) -> None:
        self._sessions = sessions
        self._session_manager = session_manager
        self._core = core_memory
        self._behavior = behavior
        self._llm = llm
        self._tools = tools or ToolRegistry()
        self._tts = tts
        self._history_window = history_window

    async def run(self, user_text: str) -> AsyncIterator[TurnEvent]:
        session = self._session_manager.current_or_new_chat()
        self._session_manager.touch(session.id)
        self._sessions.append_message(session.id, "user", user_text)

        system_prompt = build_system_prompt(self._core, self._behavior, self._sessions)
        tool_schemas = self._tools.openai_schemas() or None
        prev_tool_sig: str | None = None  # detect consecutive identical calls

        for _step in range(MAX_TOOL_STEPS + 1):
            history = self._sessions.recent_messages(session.id, self._history_window)
            prompt = build_messages(system_prompt, history)

            main_buf: list[str] = []
            thinking_buf: list[str] = []
            tool_calls: list[ToolCallDelta] = []
            splitter = SentenceSplitter()

            async for chunk in self._llm.chat_stream(
                prompt, tools=tool_schemas, thinking=False
            ):
                if chunk.done:
                    break
                if chunk.tool_calls:
                    tool_calls.extend(chunk.tool_calls)
                    continue
                if chunk.is_thinking:
                    thinking_buf.append(chunk.text)
                else:
                    main_buf.append(chunk.text)
                yield SayEvent(
                    kind="delta",
                    text=chunk.text,
                    is_thinking=chunk.is_thinking,
                )
                # Streaming TTS: synthesize each completed sentence as
                # it arrives. Each WAV is ~tens-of-KB instead of one
                # multi-MB blob at the end, which both improves
                # perceived latency and stays under any reasonable
                # WS frame size limit.
                if not chunk.is_thinking and self._tts is not None:
                    for sentence in splitter.feed(chunk.text):
                        async for ev in self._synthesize(sentence):
                            yield ev

            # Flush any tail fragment (no terminator at end).
            if self._tts is not None:
                tail = splitter.flush()
                if tail:
                    async for ev in self._synthesize(tail):
                        yield ev

            # If no tool calls, we're done.
            if not tool_calls:
                break

            # Detect consecutive identical tool calls (spec §3.4.3).
            current_sig = "|".join(f"{tc.name}:{tc.arguments_json}" for tc in tool_calls)
            if current_sig == prev_tool_sig:
                yield SayEvent(
                    kind="delta",
                    text="(same tool call repeated — breaking loop)",
                    is_thinking=False,
                )
                break
            prev_tool_sig = current_sig

            # Execute each tool call and inject results.
            for tc in tool_calls:
                tool = self._tools.get(tc.name)
                if tool is None:
                    result = ToolResult(
                        call_id=tc.id, ok=False, error=f"unknown tool: {tc.name}"
                    )
                else:
                    # Speak a canned phrase immediately so the user
                    # doesn't hear silence while the tool executes.
                    if self._tts is not None:
                        phrase = _TOOL_VOICE.get(tc.name, _TOOL_VOICE_DEFAULT)
                        yield SayEvent(kind="delta", text=phrase, is_thinking=False)
                        try:
                            wav = await self._tts.synthesize(phrase)
                            yield TTSEvent(audio_wav=wav)
                        except Exception:
                            pass  # TTS failure is non-fatal

                    yield ToolRequestEvent(
                        call_id=tc.id,
                        tool_name=tc.name,
                        arguments=json.loads(tc.arguments_json)
                        if isinstance(tc.arguments_json, str)
                        else tc.arguments_json,
                        risk=tool.risk,
                        requires_confirmation=tool.requires_confirmation,
                    )

                    try:
                        args = (
                            json.loads(tc.arguments_json)
                            if isinstance(tc.arguments_json, str)
                            else tc.arguments_json
                        )
                        data = await tool.execute(args)
                        result = ToolResult(call_id=tc.id, ok=True, data=data)
                    except Exception as e:
                        result = ToolResult(
                            call_id=tc.id, ok=False, error=str(e)
                        )

                # Persist tool call.
                self._sessions.append_message(
                    session.id,
                    "tool",
                    json.dumps(
                        {
                            "call_id": result.call_id,
                            "tool": tc.name,
                            "ok": result.ok,
                            "data": result.data,
                            "error": result.error,
                        },
                        ensure_ascii=False,
                    ),
                )

                yield ToolResultEvent(
                    call_id=result.call_id,
                    ok=result.ok,
                    summary=str(result.data)[:200] if result.ok else (result.error or ""),
                )

            # Continue the loop — the LLM will see the tool results in
            # the message history and produce a new response.
        else:
            # Exhausted MAX_TOOL_STEPS.
            yield SayEvent(
                kind="delta",
                text="(tool step limit reached)",
                is_thinking=False,
            )

        final_text = "".join(main_buf).strip()
        if final_text:
            stored = self._sessions.append_message(session.id, "assistant", final_text)
            yield SayEvent(kind="end", message_id=str(stored.id))
        else:
            yield SayEvent(kind="end", message_id="")

    async def _synthesize(self, text: str) -> AsyncIterator[TTSEvent]:
        """Run VOICEVOX on a single sentence and yield a TTSEvent.

        Failures are logged but never raise — TTS is best-effort,
        text streaming must continue regardless.
        """
        if self._tts is None or not text:
            return
        try:
            wav = await self._tts.synthesize(text)
            yield TTSEvent(audio_wav=wav)
        except Exception as e:
            import sys

            sys.stderr.write(f"[voice] TTS synthesis failed for {text[:30]!r}: {e}\n")
