import asyncio
import logging
from typing import List

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv

from .config import BotConfig
from .db import Database
from .embeds import Embeds
from .permissions import require_guild_and_channel
from .scheduler import LiveScheduler
from .sounds import SoundPlayer
from .voice_guard import VoiceGuardian


load_dotenv()


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
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self) -> None:
        await self.tree.sync(guild=discord.Object(id=self.config.guild_id))
        logging.getLogger(__name__).info("Слэш-команды синхронизированы")


async def create_bot() -> FootballBot:
    config = BotConfig.from_env()
    logging.basicConfig(level=getattr(logging, config.log_level))
    logger = logging.getLogger("bot")
    logger.info("Запуск бота…")

    db = await Database.create(path="/workspace/bot/data/bot.db")
    sounds = SoundPlayer(enabled=config.sounds_enabled)

    # API и планировщик
    scheduler = LiveScheduler(config=config, db=db, sounds=sounds)

    # Страж войса
    voice_guard = VoiceGuardian(config=config, sounds=sounds)

    bot = FootballBot(config=config, db=db, scheduler=scheduler, voice_guard=voice_guard, sounds=sounds)

    @bot.event
    async def on_ready():
        logger.info(f"Вошёл как {bot.user} (id={bot.user.id})")
        await bot.voice_guard.ensure_connected(bot)
        bot.loop.create_task(bot.scheduler.run(bot))

    @bot.event
    async def on_voice_state_update(member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.id == bot.user.id:
            await bot.voice_guard.on_self_voice_state_change(bot, before, after)

    # ===== Команды =====
    @bot.tree.command(name="help", description="Показать помощь")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def help_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        embed = Embeds.help()
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live", description="Подписаться на лайв (команда или лига)")
    @app_commands.describe(name="Команда или лига")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_cmd(interaction: discord.Interaction, name: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        await db.add_subscription(user_id=interaction.user.id, subject=name)
        embed = Embeds.success(f"Вы подписались на лайв: {name}")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-stop", description="Отменить подписку (команда или лига)")
    @app_commands.describe(name="Команда или лига")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_stop_cmd(interaction: discord.Interaction, name: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        removed = await db.remove_subscription(user_id=interaction.user.id, subject=name)
        msg = f"Подписка удалена: {name}" if removed else f"Подписка не найдена: {name}"
        embed = Embeds.info(msg)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-stop-all", description="Отменить все ваши подписки")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_stop_all_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        count = await db.clear_subscriptions(user_id=interaction.user.id)
        embed = Embeds.info(f"Удалено подписок: {count}")
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-list", description="Показать ваши подписки")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_list_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        active = await bot.scheduler.api.get_active_for_user(interaction.user.id, subs)
        embed = Embeds.subscriptions(subs, active)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-upcoming", description="Ближайшие матчи по вашим подпискам")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_upcoming_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        matches = await bot.scheduler.api.get_upcoming_for_user(interaction.user.id, subs)
        embed = Embeds.matches_list(title="Ближайшие матчи", matches=matches)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="live-now", description="Матчи в эфире по вашим подпискам")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def live_now_cmd(interaction: discord.Interaction):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        subs = await db.list_subscriptions(user_id=interaction.user.id)
        matches = await bot.scheduler.api.get_live_for_user(interaction.user.id, subs)
        embed = Embeds.matches_list(title="Сейчас в эфире", matches=matches)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="league-table", description="Показать таблицу лиги")
    @app_commands.describe(league="Название лиги")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def league_table_cmd(interaction: discord.Interaction, league: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        table = await bot.scheduler.api.get_league_table(league)
        embed = Embeds.league_table(league, table)
        await interaction.response.send_message(embed=embed)

    @bot.tree.command(name="league-streaks", description="Показать серии лиги")
    @app_commands.describe(league="Название лиги")
    @app_commands.guilds(discord.Object(id=config.guild_id))
    async def league_streaks_cmd(interaction: discord.Interaction, league: str):
        await require_guild_and_channel(interaction, config)
        await sounds.play_command_sound(bot)
        streaks = await bot.scheduler.api.get_league_streaks(league)
        embed = Embeds.league_streaks(league, streaks)
        await interaction.response.send_message(embed=embed)

    return bot


def main() -> None:
    async def runner():
        bot = await create_bot()
        await bot.start(bot.config.discord_token)

    asyncio.run(runner())


if __name__ == "__main__":
    main()