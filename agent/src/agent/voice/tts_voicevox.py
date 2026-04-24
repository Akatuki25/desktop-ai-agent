"""VOICEVOX TTS client.

VOICEVOX engine exposes an HTTP API:
  1. POST /audio_query?text=...&speaker=N  → query JSON
  2. POST /synthesis?speaker=N  body=query  → WAV bytes

This module manages the engine subprocess (spawn from vendor/voicevox/
run.exe) and exposes a simple `synthesize(text) -> bytes` async method
returning raw WAV audio.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

import httpx


class VoicevoxTTS:
    def __init__(
        self,
        *,
        binary: Path | None = None,
        host: str = "127.0.0.1",
        port: int = 50021,
        speaker: int = 1,
        startup_timeout_s: float = 60.0,
    ) -> None:
        self._binary = binary
        self._host = host
        self._port = port
        self._speaker = speaker
        self._startup_timeout_s = startup_timeout_s
        self._process: subprocess.Popen[bytes] | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self._host}:{self._port}"

    def start(self) -> None:
        """Spawn VOICEVOX engine if a binary path is given."""
        if self._binary is None:
            return
        if not self._binary.exists():
            raise FileNotFoundError(f"VOICEVOX binary not found: {self._binary}")
        if self._process is not None:
            return

        sys.stderr.write(f"[voice] spawning VOICEVOX engine: {self._binary}\n")
        self._process = subprocess.Popen(
            [str(self._binary), "--host", self._host, "--port", str(self._port)],
            stdout=subprocess.DEVNULL,
            stderr=sys.stderr,
        )
        self._wait_ready()

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self._startup_timeout_s
        while time.monotonic() < deadline:
            if self._process and self._process.poll() is not None:
                raise RuntimeError("VOICEVOX engine exited during startup")
            try:
                r = httpx.get(f"{self.base_url}/version", timeout=2.0)
                if r.status_code == 200:
                    sys.stderr.write(
                        f"[voice] VOICEVOX ready: v{r.text.strip()}\n"
                    )
                    return
            except Exception:
                pass
            time.sleep(0.5)
        self.stop()
        raise TimeoutError("VOICEVOX engine did not become ready")

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

    async def synthesize(self, text: str) -> bytes:
        """Convert text to WAV bytes via VOICEVOX HTTP API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Step 1: audio query
            query_resp = await client.post(
                f"{self.base_url}/audio_query",
                params={"text": text, "speaker": self._speaker},
            )
            query_resp.raise_for_status()
            audio_query = query_resp.json()

            # Step 2: synthesis
            synth_resp = await client.post(
                f"{self.base_url}/synthesis",
                params={"speaker": self._speaker},
                json=audio_query,
            )
            synth_resp.raise_for_status()
            return synth_resp.content
