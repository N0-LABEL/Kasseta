import asyncio
import contextlib
from typing import Optional, Dict, Set, List

import discord
from discord.ext import commands, tasks
from loguru import logger

from bot import config
from bot.services.subscription_store import SubscriptionStore
from bot.services.football_provider import FootballProvider


class FootballBot(commands.Bot):
	def __init__(self) -> None:
		intents = discord.Intents.none()
		intents.guilds = True
		intents.voice_states = True
		super().__init__(command_prefix=commands.when_mentioned_or("/"), intents=intents)

		self.subscription_store = SubscriptionStore()
		self.football = FootballProvider(config.FOOTBALL_API_PROVIDER, config.FOOTBALL_API_KEY)
		self._live_last_sent: Dict[int, Set[str]] = {}
		self.target_voice_channel_id: Optional[int] = config.TARGET_VOICE_CHANNEL_ID
		self.guild_id_for_register: Optional[int] = config.TARGET_GUILD_ID

	async def setup_hook(self) -> None:
		await self.load_extension("bot.cogs.basic")
		await self.load_extension("bot.cogs.live")
		await self.load_extension("bot.cogs.league")

		# Ограниченная синхронизация команд на один сервер (если указан)
		if self.guild_id_for_register:
			guild_obj = discord.Object(id=self.guild_id_for_register)
			self.tree.copy_global_to(guild=guild_obj)
			await self.tree.sync(guild=guild_obj)
			logger.info("Слэш-команды синхронизированы с гильдией {guild}", guild=self.guild_id_for_register)
		else:
			await self.tree.sync()
			logger.info("Слэш-команды синхронизированы глобально")

		self.ensure_voice_stay.start()
		self.live_updates_loop.start()

	async def on_ready(self) -> None:
		logger.info("Вошёл как {user} (ID: {id})", user=self.user, id=self.user.id if self.user else None)
		await self.ensure_connected_to_voice()

	async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
		if not self.user or member.id != self.user.id:
			return
		# Бота переместили/выкинули — возвращаем в целевой канал
		await self.ensure_connected_to_voice(force=True)

	async def ensure_connected_to_voice(self, force: bool = False) -> None:
		if not self.target_voice_channel_id:
			return
		guilds: List[discord.Guild] = [g for g in self.guilds if g.get_channel(self.target_voice_channel_id)]
		if not guilds:
			logger.warning("Не найден голосовой канал с ID {cid} среди гильдий бота", cid=self.target_voice_channel_id)
			return
		guild = guilds[0]
		channel = guild.get_channel(self.target_voice_channel_id)
		if not isinstance(channel, discord.VoiceChannel):
			logger.warning("Канал {cid} не является голосовым", cid=self.target_voice_channel_id)
			return

		voice_client: Optional[discord.VoiceClient] = guild.voice_client
		if voice_client and voice_client.is_connected():
			if voice_client.channel and voice_client.channel.id == channel.id and not force:
				return
			with contextlib.suppress(Exception):
				await voice_client.disconnect(force=True)

		try:
			await channel.connect(reconnect=True)
			logger.info("Подключён к голосовому каналу {name} ({id})", name=channel.name, id=channel.id)
		except Exception as e:
			logger.error("Не удалось подключиться к голосовому каналу: {e}", e=e)

	@tasks.loop(seconds=max(10, config.LIVE_POLL_SECONDS))
	async def live_updates_loop(self) -> None:
		for channel_id in self.subscription_store.get_channels():
			keys = self.subscription_store.get_subscriptions(channel_id)
			if not keys:
				continue
			try:
				updates = await self.football.get_live_scores_for_keys(keys)
			except Exception as e:
				logger.error("Ошибка получения лайв-обновлений: {e}", e=e)
				continue

			if not updates:
				continue

			channel = self.get_channel(channel_id)
			if not isinstance(channel, (discord.TextChannel, discord.Thread)):
				continue

			last_set = self._live_last_sent.setdefault(channel_id, set())
			for upd in updates:
				if upd in last_set:
					continue
				try:
					await channel.send(upd)
					last_set.add(upd)
				except Exception as e:
					logger.error("Не удалось отправить сообщение в канал {cid}: {e}", cid=channel_id, e=e)

	@tasks.loop(seconds=15)
	async def ensure_voice_stay(self) -> None:
		await self.ensure_connected_to_voice()

	@ensure_voice_stay.before_loop
	async def before_voice(self) -> None:
		await self.wait_until_ready()

	@live_updates_loop.before_loop
	async def before_updates(self) -> None:
		await self.wait_until_ready()

	async def close(self) -> None:
		with contextlib.suppress(Exception):
			await self.football.aclose()
		await super().close()


def main() -> None:
	if not config.DISCORD_TOKEN:
		raise SystemExit("DISCORD_TOKEN не задан")
	bot = FootballBot()
	bot.run(config.DISCORD_TOKEN, log_handler=None)


if __name__ == "__main__":
	main()