from __future__ import annotations

import os
import discord


ASSETS_DIR = "/workspace/assets/sounds"


class SoundPlayer:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def _get_voice_client(self, bot: discord.Client) -> discord.VoiceClient | None:
        for vc in bot.voice_clients:
            if vc.is_connected():
                return vc
        return None

    async def _play_file(self, bot: discord.Client, filename: str) -> None:
        if not self.enabled:
            return
        vc = self._get_voice_client(bot)
        if vc is None:
            return
        path = os.path.join(ASSETS_DIR, filename)
        if not os.path.isfile(path):
            return
        if vc.is_playing():
            return
        try:
            vc.play(discord.FFmpegPCMAudio(path))
        except Exception:
            pass

    async def play_command_sound(self, bot: discord.Client) -> None:
        await self._play_file(bot, "command.wav")

    async def play_goal(self, bot: discord.Client) -> None:
        await self._play_file(bot, "goal.wav")

    async def play_end(self, bot: discord.Client) -> None:
        await self._play_file(bot, "end.wav")