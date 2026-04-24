"""Agent daemon entrypoint.

Lifecycle:
1. CLI parses --port / --token (both optional; --port 0 picks a free
   port and --token is generated if omitted).
2. If LLAMA_SERVER_URL is set, use that as the LLM backend. Otherwise
   spawn llama-server from LLAMA_SERVER_BIN + LLAMA_MODEL.
3. factory.build_app wires memory, LLM, tools, TTS, scheduler — see
   factory.py for the full assembly.
4. The daemon prints one JSON line {"event": "ready", "port": N} so
   Tauri can parse the bound port, then runs uvicorn in the
   foreground. On shutdown it kills the llama-server child (if any).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
from pathlib import Path
from types import FrameType

import uvicorn

from agent.core.config import Settings
from agent.factory import build_app
from agent.llm.llama_server_process import LlamaServerConfig, LlamaServerProcess


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _data_dir() -> Path:
    env = os.environ.get("AGENT_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / "AppData" / "Roaming" / "desktop-ai-agent"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--port", type=int, default=0, help="ws port (0 = ephemeral)")
    parser.add_argument("--token", default=None, help="auth token (auto-generated if omitted)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    token = args.token or secrets.token_urlsafe(32)
    port = args.port or _pick_port()

    # --- llama-server ---
    external_url = os.environ.get("LLAMA_SERVER_URL", "").strip()
    llama_proc: LlamaServerProcess | None = None
    if external_url:
        sys.stderr.write(f"[agent] using external llama-server at {external_url}\n")
        llama_url = external_url
    else:
        llama_bin_str = os.environ.get("LLAMA_SERVER_BIN", "")
        llama_model_str = os.environ.get("LLAMA_MODEL", "")
        if not llama_bin_str or not llama_model_str:
            raise SystemExit(
                "[agent] Either set LLAMA_SERVER_URL for an external server, "
                "or set both LLAMA_SERVER_BIN and LLAMA_MODEL to auto-spawn."
            )
        llama_bin = Path(llama_bin_str)
        llama_model = Path(llama_model_str)
        if not llama_bin.exists():
            raise SystemExit(f"[agent] LLAMA_SERVER_BIN not found: {llama_bin}")
        if not llama_model.exists():
            raise SystemExit(f"[agent] LLAMA_MODEL not found: {llama_model}")
        llama_proc = LlamaServerProcess(
            LlamaServerConfig(binary=llama_bin, model=llama_model)
        )
        llama_proc.start()
        llama_url = llama_proc.base_url

    def _shutdown(signum: int, _frame: FrameType | None) -> None:
        sys.stderr.write(f"[agent] signal {signum}, stopping\n")
        if llama_proc is not None:
            llama_proc.stop()
        sys.exit(0)

    if sys.platform != "win32":
        import signal

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)

    try:
        # --- Build the full app via factory ---
        settings = Settings(
            data_dir=_data_dir(),
            llm_backend="llama_server",
            llama_server_url=llama_url,
        )
        app = build_app(token=token, settings=settings)

        ready: dict[str, object] = {"event": "ready", "port": port}
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
