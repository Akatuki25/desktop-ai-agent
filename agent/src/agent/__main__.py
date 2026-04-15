"""Agent daemon entrypoint.

Lifecycle:
1. CLI parses --port / --token (both optional; --port 0 picks a free
   port and --token is generated if omitted).
2. Memory layer is opened under AGENT_DATA_DIR (or the Windows
   roaming appdata fallback).
3. llama-server is spawned as a child process using LLAMA_SERVER_BIN +
   LLAMA_MODEL from the environment; the daemon refuses to start if
   either is missing (there is no stub backend — see docs §3.4.2).
4. Orchestrator + LLM backend are wired together and handed to the
   FastAPI WebSocket server.
5. The daemon prints one JSON line {"event": "ready", "port": N} so
   Tauri can parse the bound port, then runs uvicorn in the
   foreground. On shutdown it kills the llama-server child.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import socket
import sys
from pathlib import Path
from types import FrameType

import uvicorn

from agent.interface.server import create_app
from agent.llm import LlamaServerBackend
from agent.llm.llama_server_process import LlamaServerConfig, LlamaServerProcess
from agent.memory import BehaviorConfig, CoreMemory, Database, SessionRepository
from agent.orchestrator import SessionManager, TurnLoop


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _data_dir() -> Path:
    env = os.environ.get("AGENT_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / "AppData" / "Roaming" / "desktop-ai-agent"


def _require_env_path(name: str) -> Path:
    raw = os.environ.get(name)
    if not raw:
        raise SystemExit(
            f"[agent] ${name} is not set. scripts/activate.ps1 configures this, "
            f"or export it manually to the llama.cpp binary / GGUF model path."
        )
    path = Path(raw)
    if not path.exists():
        raise SystemExit(f"[agent] ${name} points at a missing file: {path}")
    return path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--port", type=int, default=0, help="ws port (0 = ephemeral)")
    parser.add_argument("--token", default=None, help="auth token (auto-generated if omitted)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    token = args.token or secrets.token_urlsafe(32)
    port = args.port or _pick_port()

    # --- memory ---
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(data_dir / "db.sqlite")
    repo = SessionRepository(db)
    core = CoreMemory(db)
    behavior = BehaviorConfig(db)
    if not core.all():
        core.set("persona", "You are a friendly desktop companion agent.")
    if not behavior.all():
        behavior.set("tone", "warm and concise")

    # --- llama-server ---
    # If LLAMA_SERVER_URL is set, assume the caller already has a
    # llama-server running (useful for dev: keep a model-loaded server
    # warm across daemon restarts). Otherwise spawn + supervise a
    # child process ourselves.
    external_url = os.environ.get("LLAMA_SERVER_URL", "").strip()
    llama_proc: LlamaServerProcess | None = None
    if external_url:
        sys.stderr.write(f"[agent] using external llama-server at {external_url}\n")
        base_url = external_url
    else:
        llama_bin = _require_env_path("LLAMA_SERVER_BIN")
        llama_model = _require_env_path("LLAMA_MODEL")
        llama_proc = LlamaServerProcess(
            LlamaServerConfig(binary=llama_bin, model=llama_model)
        )
        llama_proc.start()
        base_url = llama_proc.base_url

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        sys.stderr.write(f"[agent] received signal {signum}, stopping llama-server\n")
        if llama_proc is not None:
            llama_proc.stop()
        sys.exit(0)

    if sys.platform != "win32":
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

    try:
        # --- LLM backend + orchestrator + WS ---
        backend = LlamaServerBackend(base_url=base_url)
        loop = TurnLoop(
            sessions=repo,
            session_manager=SessionManager(repo),
            core_memory=core,
            behavior=behavior,
            llm=backend,
        )
        app = create_app(token=token, turn_loop=loop)

        ready = {"event": "ready", "port": port}
        if args.token is None:
            ready["token"] = token
        sys.stdout.write(json.dumps(ready) + "\n")
        sys.stdout.flush()

        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level=args.log_level,
            access_log=False,
        )
    finally:
        if llama_proc is not None:
            llama_proc.stop()


if __name__ == "__main__":
    main()
