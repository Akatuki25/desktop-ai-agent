"""Entrypoint for the agent daemon.

Tauri spawns this process, passing --token and reading the first stdout line
to discover the bound port. Use --port 0 to let the OS pick a free port.
"""

from __future__ import annotations

import argparse
import json
import secrets
import socket
import sys

import uvicorn

from agent.interface.server import create_app


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="agent")
    parser.add_argument("--port", type=int, default=0, help="port (0 = ephemeral)")
    parser.add_argument("--token", default=None, help="auth token (auto-generated if omitted)")
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args(argv)

    token = args.token or secrets.token_urlsafe(32)
    port = args.port or _pick_port()

    app = create_app(token=token)

    ready = {"event": "ready", "port": port}
    if args.token is None:
        # Only leak the generated token in standalone/debug mode.
        ready["token"] = token
    sys.stdout.write(json.dumps(ready) + "\n")
    sys.stdout.flush()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level=args.log_level, access_log=False)


if __name__ == "__main__":
    main()
