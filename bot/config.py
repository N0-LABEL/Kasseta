from __future__ import annotations

import os
from dataclasses import dataclass


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y"}


@dataclass
class BotConfig:
    discord_token: str
    guild_id: int
    voice_channel_id: int
    commands_text_channel_id: int
    mirror_text_channel_id: int
    api_provider: str
    api_key: str | None
    timezone: str
    poll_seconds: int
    log_level: str
    sounds_enabled: bool

    @staticmethod
    def from_env() -> "BotConfig":
        return BotConfig(
            discord_token=os.environ.get("DISCORD_TOKEN", ""),
            guild_id=int(os.environ.get("GUILD_ID", "0") or 0),
            voice_channel_id=int(os.environ.get("VOICE_CHANNEL_ID", "0") or 0),
            commands_text_channel_id=int(os.environ.get("COMMANDS_TEXT_CHANNEL_ID", "0") or 0),
            mirror_text_channel_id=int(os.environ.get("MIRROR_TEXT_CHANNEL_ID", "0") or 0),
            api_provider=os.environ.get("FOOTBALL_API_PROVIDER", "mock"),
            api_key=os.environ.get("FOOTBALL_API_KEY"),
            timezone=os.environ.get("TZ", "Europe/Moscow"),
            poll_seconds=int(os.environ.get("POLL_SECONDS", "30") or 30),
            log_level=os.environ.get("LOG_LEVEL", "INFO").upper(),
            sounds_enabled=_bool(os.environ.get("SOUNDS_ENABLED", "true"), True),
        )