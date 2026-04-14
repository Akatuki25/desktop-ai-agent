"""Runtime configuration loaded from env vars."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AGENT_", case_sensitive=False)

    log_level: str = Field(default="INFO")
    data_dir: Path = Field(default=Path.home() / "AppData" / "Roaming" / "desktop-ai-agent")
