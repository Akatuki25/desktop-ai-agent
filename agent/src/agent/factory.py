"""Wire the daemon together from config.

This is the one place that knows all layers — memory, LLM, orchestrator,
interface — so both __main__.py and tests can build a ready-to-serve
FastAPI app in one call.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from agent.core.config import Settings
from agent.interface.server import create_app
from agent.llm import FakeLLMBackend, LlamaServerBackend
from agent.llm.backend import LLMBackend
from agent.memory import BehaviorConfig, CoreMemory, Database, SessionRepository
from agent.orchestrator import SessionManager, TurnLoop


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
    turn_loop = TurnLoop(
        sessions=repo,
        session_manager=SessionManager(repo),
        core_memory=core,
        behavior=behavior,
        llm=llm,
    )

    return create_app(token=token, turn_loop=turn_loop)
