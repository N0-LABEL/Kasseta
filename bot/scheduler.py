from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, Any, List, Set

import discord

from .config import BotConfig
from .db import Database
from .embeds import Embeds
from .api import FootballAPI
from .sounds import SoundPlayer


class LiveScheduler:
    def __init__(self, config: BotConfig, db: Database, sounds: SoundPlayer) -> None:
        self.config = config
        self.db = db
        self.sounds = sounds
        self.api = FootballAPI(provider=config.api_provider, api_key=config.api_key)
        self._running = False
        self._log = logging.getLogger("scheduler")

    async def run(self, bot: discord.Client) -> None:
        if self._running:
            return
        self._running = True
        self._log.info("Запущен планировщик обновлений")
        while self._running:
            try:
                await self._tick(bot)
            except Exception as e:
                self._log.exception("Ошибка в планировщике: %s", e)
            await asyncio.sleep(self.config.poll_seconds)

    async def _tick(self, bot: discord.Client) -> None:
        goals, finished = await self.api.poll_changes()

        # Отправка событий
        if goals:
            await self._broadcast_events(bot, goals, is_goal=True)
        if finished:
            await self._broadcast_events(bot, finished, is_goal=False)

        # Очистка завершённых
        for m in finished:
            await self.db.remove_match_state(m["id"])

    async def _broadcast_events(self, bot: discord.Client, events: List[Dict[str, Any]], is_goal: bool) -> None:
        mirror_channel = bot.get_channel(self.config.mirror_text_channel_id)
        for match in events:
            # Собрать пользователей, кому релевантно событие
            audience: Set[int] = await self._collect_audience(match)
            embed = Embeds.goal(match) if is_goal else Embeds.match_end(match)

            # Звук
            if is_goal:
                await self.sounds.play_goal(bot)
            else:
                await self.sounds.play_end(bot)

            # DM каждому
            for user_id in audience:
                user = bot.get_user(user_id) or await bot.fetch_user(user_id)
                if user:
                    try:
                        await user.send(embed=embed)
                    except Exception:
                        pass

            # Дублирование в канал
            if isinstance(mirror_channel, discord.TextChannel):
                try:
                    await mirror_channel.send(embed=embed)
                except Exception:
                    pass

    async def _collect_audience(self, match: Dict[str, Any]) -> Set[int]:
        audience: Set[int] = set()
        subjects_map = await self._get_all_subjects()
        for user_id, subjects in subjects_map.items():
            if self.api._match_matches_subjects(match, subjects):
                audience.add(user_id)
        return audience

    async def _get_all_subjects(self) -> Dict[int, List[str]]:
        # Inefficient but fine for demo: read all users by scanning DB per user id not stored. We'll over-approximate.
        # We lack a users table; emulate by reading all rows.
        result: Dict[int, List[str]] = {}
        async with self.db._conn.execute("SELECT user_id, subject FROM subscriptions") as cur:
            rows = await cur.fetchall()
            for uid, subject in rows:
                result.setdefault(int(uid), []).append(subject)
        return result