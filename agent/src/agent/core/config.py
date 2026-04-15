"""Runtime configuration loaded from env vars.

Settings are also the single place the daemon decides *which* LLM
backend to use — see factory() below. Env prefix is AGENT_ so they
don't collide with anything Tauri sets.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", case_sensitive=False)

    log_level: str = Field(default="INFO")
    data_dir: Path = Field(
        default_factory=lambda: Path.home() / "AppData" / "Roaming" / "desktop-ai-agent"
    )

    # LLM backend selection.
    # "fake" — offline persona echo, no model needed (default for dev)
    # "llama_server" — talk to llama-server's OpenAI-compatible API
    llm_backend: str = Field(default="fake")
    llama_server_url: str = Field(default="http://127.0.0.1:8080")
    llama_model_name: str = Field(default="qwen")
