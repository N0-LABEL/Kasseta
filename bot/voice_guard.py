from __future__ import annotations

import asyncio
import discord
from .config import BotConfig


class VoiceGuardian:
    def __init__(self, config: BotConfig, sounds) -> None:
        self.config = config
        self.sounds = sounds
        self._lock = asyncio.Lock()

    async def ensure_connected(self, bot: discord.Client) -> None:
        async with self._lock:
            guild = bot.get_guild(self.config.guild_id)
            if guild is None:
                return
            channel = guild.get_channel(self.config.voice_channel_id)
            if not isinstance(channel, discord.VoiceChannel):
                return
            already = False
            for vc in bot.voice_clients:
                if vc.guild.id == guild.id and vc.channel and vc.channel.id == channel.id:
                    already = True
                    break
            if already:
                return
            try:
                await channel.connect(reconnect=True)
            except Exception:
                pass

    async def on_self_voice_state_change(self, bot: discord.Client, before: discord.VoiceState, after: discord.VoiceState) -> None:
        # If disconnected or moved, go back to the configured channel
        channel_id = after.channel.id if after and after.channel else None
        if channel_id != self.config.voice_channel_id:
            await asyncio.sleep(1)
            await self.ensure_connected(bot)