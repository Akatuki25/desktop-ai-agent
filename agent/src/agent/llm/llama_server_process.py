"""Spawn and supervise llama-server as a child process.

Per docs/architecture.md §3, the daemon owns the llama-server lifetime:
it spawns the binary with the configured GGUF model, waits for the
OpenAI-compatible /v1/models endpoint to answer, and tears the process
down on shutdown. The caller should instantiate this once at startup
and pass the resulting base_url to LlamaServerBackend.
"""

from __future__ import annotations

import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True)
class LlamaServerConfig:
    binary: Path
    model: Path
    host: str = "127.0.0.1"
    port: int = 0  # 0 = pick free
    ctx_size: int = 8192
    threads: int | None = None
    startup_timeout_s: float = 120.0


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LlamaServerProcess:
    def __init__(self, config: LlamaServerConfig) -> None:
        if not config.binary.exists():
            raise FileNotFoundError(f"llama-server binary not found: {config.binary}")
        if not config.model.exists():
            raise FileNotFoundError(f"GGUF model not found: {config.model}")
        self._config = config
        self._process: subprocess.Popen[bytes] | None = None
        self._port: int = 0

    @property
    def base_url(self) -> str:
        if not self._port:
            raise RuntimeError("llama-server not started")
        return f"http://{self._config.host}:{self._port}"

    def start(self) -> None:
        if self._process is not None:
            return
        port = self._config.port or _pick_free_port()
        args: list[str] = [
            str(self._config.binary),
            "-m",
            str(self._config.model),
            "--host",
            self._config.host,
            "--port",
            str(port),
            "-c",
            str(self._config.ctx_size),
            "--jinja",
        ]
        if self._config.threads is not None:
            args += ["-t", str(self._config.threads)]

        sys.stderr.write(f"[agent] spawning llama-server: {' '.join(args)}\n")
        self._process = subprocess.Popen(
            args,
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
        )
        self._port = port
        self._wait_ready()

    def _wait_ready(self) -> None:
        url = f"{self.base_url}/v1/models"
        deadline = time.monotonic() + self._config.startup_timeout_s
        last_err: Exception | None = None
        while time.monotonic() < deadline:
            if self._process is None or self._process.poll() is not None:
                raise RuntimeError(
                    "llama-server exited before becoming ready"
                    f" (exit code {self._process.returncode if self._process else 'n/a'})"
                )
            try:
                r = httpx.get(url, timeout=2.0)
                if r.status_code == 200:
                    sys.stderr.write(f"[agent] llama-server ready at {self.base_url}\n")
                    return
            except Exception as e:
                last_err = e
            time.sleep(0.5)
        self.stop()
        raise TimeoutError(
            f"llama-server did not answer /v1/models within "
            f"{self._config.startup_timeout_s}s (last error: {last_err})"
        )

    def stop(self) -> None:
        if self._process is None:
            return
        try:
            self._process.terminate()
            try:
                self._process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self._process.kill()
                self._process.wait(timeout=2.0)
        finally:
            self._process = None
