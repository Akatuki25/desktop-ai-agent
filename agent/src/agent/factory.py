"""Wire the daemon together from config.

This is the one place that knows all layers — memory, LLM, orchestrator,
interface — so both __main__.py and tests can build a ready-to-serve
FastAPI app in one call.
"""

from __future__ import annotations

import os
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
        core.set("persona", "You are a friendly desktop companion agent.")
    if not behavior.all():
        behavior.set("tone", "warm and concise")

    llm = make_llm_backend(settings)

    # Build tool registry with built-in tools.
    search = MemorySearch(db)
    registry = ToolRegistry()
    registry.register(MemorySearchTool(search))
    registry.register(MemoryUpsertTool(core))
    registry.register(AskUserTool())

    # TTS: try to start VOICEVOX if the binary is configured.
    tts: VoicevoxTTS | None = None
    vv_bin = os.environ.get("VOICEVOX_BIN", "")
    if vv_bin and Path(vv_bin).exists():
        tts = VoicevoxTTS(binary=Path(vv_bin))
        try:
            tts.start()
        except Exception as e:
            import sys

            sys.stderr.write(f"[factory] VOICEVOX start failed: {e} — TTS disabled\n")
            tts = None

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
    scheduler.start()

    # Store scheduler on app state so __main__ can stop it on shutdown.
    app.state.scheduler = scheduler

    return app
