"""Wire the daemon together from config.

This is the one place that knows all layers — memory, LLM, orchestrator,
interface — so both __main__.py and tests can build a ready-to-serve
FastAPI app in one call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI

from agent.core.config import Settings
from agent.interface.server import create_app
from agent.llm import FakeLLMBackend, LlamaServerBackend
from agent.llm.backend import LLMBackend
from agent.memory import BehaviorConfig, CoreMemory, Database, MemorySearch, SessionRepository
from agent.orchestrator import SessionManager, TurnLoop
from agent.scheduler.cron import CronScheduler
from agent.scheduler.proactive import ProactiveDriver
from agent.tools import ToolRegistry
from agent.tools.ask_user import AskUserTool
from agent.tools.memory_tools import MemorySearchTool, MemoryUpsertTool
from agent.tools.schedule_tools import ScheduleRegisterTool
from agent.tools.web_tools import WebFetchTool, WebOpenTool, WebSearchTool
from agent.voice.tts_voicevox import VoicevoxTTS


def make_llm_backend(settings: Settings) -> LLMBackend:
    if settings.llm_backend == "llama_server":
        return LlamaServerBackend(
            base_url=settings.llama_server_url,
            model=settings.llama_model_name,
        )
    return FakeLLMBackend.persona_mode()


def build_app(token: str, *, settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    db_path: Path = settings.data_dir / "db.sqlite"
    db = Database(db_path)
    repo = SessionRepository(db)
    core = CoreMemory(db)
    behavior = BehaviorConfig(db)

    # Seed minimal persona/behavior on first run so the system prompt
    # isn't empty.
    if not core.all():
        core.set("persona", "ずんだもん — 東北地方のずんだ餅の精霊。明るく元気で好奇心旺盛。")
    if not behavior.all():
        behavior.set("tone", "元気で親しみやすい。語尾に「〜のだ」を使う。2-3文で簡潔に。")

    from agent.llm.locked import LockedLLMBackend

    raw_llm = make_llm_backend(settings)
    llm = LockedLLMBackend(raw_llm)

    # Build tool registry with built-in tools.
    search = MemorySearch(db)
    registry = ToolRegistry()
    registry.register(MemorySearchTool(search))
    registry.register(MemoryUpsertTool(core))
    registry.register(AskUserTool())
    registry.register(WebSearchTool())
    registry.register(WebFetchTool())
    registry.register(WebOpenTool())

    # TTS: connect to VOICEVOX if reachable, or spawn from binary.
    tts: VoicevoxTTS | None = None
    vv_port = int(os.environ.get("VOICEVOX_PORT", "50021"))
    vv_bin = os.environ.get("VOICEVOX_BIN", "")
    # First check if VOICEVOX is already running (dev workflow: started
    # separately so model stays warm across daemon restarts).
    try:
        import httpx

        r = httpx.get(f"http://127.0.0.1:{vv_port}/version", timeout=2.0)
        if r.status_code == 200:
            sys.stderr.write(
                f"[factory] VOICEVOX already running (v{r.text.strip()}) — reusing\n"
            )
            tts = VoicevoxTTS(host="127.0.0.1", port=vv_port, speaker=1)
    except Exception:
        pass

    if tts is None and vv_bin and Path(vv_bin).exists():
        tts = VoicevoxTTS(binary=Path(vv_bin), port=vv_port, speaker=1)
        try:
            tts.start()
            sys.stderr.write("[factory] VOICEVOX spawned\n")
        except Exception as e:
            sys.stderr.write(f"[factory] VOICEVOX start failed: {e} — TTS disabled\n")
            tts = None

    if tts is None:
        sys.stderr.write("[factory] TTS disabled (no VOICEVOX)\n")

    turn_loop = TurnLoop(
        sessions=repo,
        session_manager=SessionManager(repo, llm),
        core_memory=core,
        behavior=behavior,
        llm=llm,
        tools=registry,
        tts=tts,
    )

    app = create_app(token=token, turn_loop=turn_loop)

    # Scheduler + proactive driver — needs the broadcast function from the
    # server for pushing notifications to all connected WS clients.
    broadcast_fn = app.state.broadcast
    proactive = ProactiveDriver(
        repo=repo, core=core, behavior=behavior, llm=llm, broadcast=broadcast_fn,
    )
    scheduler = CronScheduler(db, callback=proactive.fire)
    registry.register(ScheduleRegisterTool(scheduler))

    # Defer scheduler.start() until the event loop is running (uvicorn).
    @app.on_event("startup")
    async def _start_scheduler() -> None:
        scheduler.start()

    @app.on_event("shutdown")
    async def _stop_scheduler() -> None:
        scheduler.stop()

    app.state.scheduler = scheduler

    return app
