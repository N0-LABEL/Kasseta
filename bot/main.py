import asyncio
import logging
import os
from typing import List

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv, find_dotenv

from .config import BotConfig
from .db import Database
from .embeds import Embeds
from .permissions import require_guild_and_channel
from .scheduler import LiveScheduler
from .sounds import SoundPlayer
from .voice_guard import VoiceGuardian


load_dotenv(find_dotenv())


intents = discord.Intents.default()
intents.guilds = True
intents.members = True


class FootballBot(commands.Bot):
    def __init__(self, config: BotConfig, db: Database, scheduler: LiveScheduler, voice_guard: VoiceGuardian, sounds: SoundPlayer) -> None:
        super().__init__(command_prefix="!", intents=intents)
        self.config = config
        self.db = db
        self.scheduler = scheduler
        self.voice_guard = voice_guard
        self.sounds = sounds
        # self.tree is provided by commands.Bot in discord.py v2

    async def setup_hook(self) -> None:
        # Global sync (may take time to propagate) plus targeted guild sync if задан
        try:
            if self.config.guild_id:
                await self.tree.sync(guild=discord.Object(id=self.config.guild_id))
            else:
                await self.tree.sync()
            logging.getLogger(__name__).info("Слэш-команды синхронизированы")
        except Exception as e:
            logging.getLogger(__name__).exception("Ошибка синхронизации команд: %s", e)


async def create_bot() -> FootballBot:
    config = BotConfig.from_env()
    logging.basicConfig(level=getattr(logging, config.log_level))
    logger = logging.getLogger("bot")
    logger.info("Запуск бота…")

    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    db_path = os.path.join(base_dir, "bot", "data", "bot.db")

    db = await Database.create(path=db_path)
    sounds = SoundPlayer(enabled=config.sounds_enabled)

    # API и планировщик
    scheduler = LiveScheduler(config=config, db=db, sounds=sounds)

    # Страж войса
    voice_guard = VoiceGuardian(config=config, sounds=sounds)

    bot = FootballBot(config=config, db=db, scheduler=scheduler, voice_guard=voice_guard, sounds=sounds)

    @bot.event
    async def on_ready():
        logger.info(f"Вошёл как {bot.user} (id={bot.user.id})")
        # Быстрая синхронизация на все гильдии, где есть бот (мгновенно)
        try:
            for guild in bot.guilds:
                await bot.tree.sync(guild=guild)
            # Обновим и глобальные, чтобы не было рассинхронизации
            await bot.tree.sync()
        except Exception:
            pass
        await bot.voice_guard.ensure_connected(bot)
        bot.loop.create_task(bot.scheduler.run(bot))

    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id == bot.user.id:
            await bot.voice_guard.on_self_voice_state_change(bot, before, after)

    # ===== Команды =====
    async def _subject_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        suggestions = await bot.scheduler.api.get_subject_suggestions(current)
        return [app_commands.Choice(name=s, value=s) for s in suggestions]

    async def _league_autocomplete(interaction: discord.Interaction, current: str) -> List[app_commands.Choice[str]]:
        suggestions = await bot.scheduler.api.get_league_suggestions(current)
        return [app_commands.Choice(name=s, value=s) for s in suggestions]

    @bot.tree.command(name="help", description="Показать помощь")
    async def help_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        embed = Embeds.help()
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live", description="Подписаться на лайв (команда или лига)")
    @app_commands.describe(name="Команда или лига")
    @app_commands.rename(name="team-or-league-name")
    @app_commands.autocomplete(name=_subject_autocomplete)
    async def live_cmd(interaction: discord.Interaction, name: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        verified = await bot.scheduler.api.verify_subject(name)
        if not verified:
            await interaction.response.send_message(embed=Embeds.error("Не удалось распознать команду или лигу. Выберите из подсказки или укажите точнее."))
            return
        kind, canonical = verified
        await db.add_subscription(user_id=interaction.user.id, subject=canonical)
        embed = Embeds.success(f"Вы подписались на лайв: {canonical}")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-stop", description="Отменить подписку (команда или лига)")
    @app_commands.describe(name="Команда или лига")
    @app_commands.rename(name="team-or-league-name")
    @app_commands.autocomplete(name=_subject_autocomplete)
    async def live_stop_cmd(interaction: discord.Interaction, name: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        verified = await bot.scheduler.api.verify_subject(name)
        if not verified:
            await interaction.response.send_message(embed=Embeds.error("Не удалось распознать предмет подписки."))
            return
        _kind, canonical = verified
        removed = await db.remove_subscription(user_id=interaction.user.id, subject=canonical)
        msg = f"Подписка удалена: {canonical}" if removed else f"Подписка не найдена: {canonical}"
        embed = Embeds.info(msg)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-stop-all", description="Отменить все ваши подписки")
    async def live_stop_all_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        count = await db.clear_subscriptions(user_id=interaction.user.id)
        embed = Embeds.info(f"Удалено подписок: {count}")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-list", description="Показать ваши подписки")
    async def live_list_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        active = await bot.scheduler.api.get_active_for_user(interaction.user.id, subs)
        embed = Embeds.subscriptions(subs, active)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-upcoming", description="Ближайшие матчи по вашим подпискам")
    async def live_upcoming_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        matches = await bot.scheduler.api.get_upcoming_for_user(interaction.user.id, subs)
        embed = Embeds.matches_list(title="Ближайшие матчи", matches=matches)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-now", description="Матчи в эфире по вашим подпискам")
    async def live_now_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        matches = await bot.scheduler.api.get_live_for_user(interaction.user.id, subs)
        embed = Embeds.matches_list(title="Сейчас в эфире", matches=matches)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="league-table", description="Показать таблицу лиги")
    @app_commands.describe(league="Название лиги")
    @app_commands.rename(league="league-name")
    @app_commands.autocomplete(league=_league_autocomplete)
    async def league_table_cmd(interaction: discord.Interaction, league: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        table = await bot.scheduler.api.get_league_table(league)
        embed = Embeds.league_table(league, table)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="league-streaks", description="Показать серии лиги")
    @app_commands.describe(league="Название лиги")
    @app_commands.rename(league="league-name")
    @app_commands.autocomplete(league=_league_autocomplete)
    async def league_streaks_cmd(interaction: discord.Interaction, league: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        streaks = await bot.scheduler.api.get_league_streaks(league)
        embed = Embeds.league_streaks(league, streaks)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="next", description="Ближайший(ие) матч(и) по команде или лиге")
    @app_commands.describe(subject="Команда или лига")
    @app_commands.autocomplete(subject=_subject_autocomplete)
    async def next_cmd(interaction: discord.Interaction, subject: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        matches = await bot.scheduler.api.get_next_for_subject(subject)
        if not matches:
            await interaction.response.send_message(embed=Embeds.info("Ничего не найдено"))
            return
        title = "Ближайший матч" if len(matches) == 1 else "Ближайшие матчи"
        embed = Embeds.matches_list(title=title, matches=matches)
        await interaction.response.send_message(embed=embed)

    return bot


def main() -> None:
    async def runner():
        bot = await create_bot()
        await bot.start(bot.config.discord_token)

    asyncio.run(runner())


if __name__ == "__main__":
    main()