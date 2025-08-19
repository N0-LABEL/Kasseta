import discord
from discord import app_commands
from discord.ext import commands


class LiveCog(commands.Cog):
	def __init__(self, bot: commands.Bot) -> None:
		self.bot = bot

	@app_commands.describe(query="Название команды или лиги")
	@app_commands.command(name="live", description="Подписаться на лайв-счёты для команды или лиги в этом канале")
	async def live_subscribe(self, interaction: discord.Interaction, query: str) -> None:
		added = self.bot.subscription_store.add_subscription(interaction.channel_id, query)
		if added:
			await interaction.response.send_message(
				f"✅ Подписка добавлена: '{query}'. Я буду отправлять лайв-обновления в этот канал.", ephemeral=False
			)
		else:
			await interaction.response.send_message(
				f"ℹ️ Подписка уже существует: '{query}'.", ephemeral=True
			)

	@app_commands.describe(query="Название команды или лиги")
	@app_commands.command(name="live-stop", description="Остановить лайв для указанной подписки в этом канале")
	async def live_stop(self, interaction: discord.Interaction, query: str) -> None:
		removed = self.bot.subscription_store.remove_subscription(interaction.channel_id, query)
		if removed:
			await interaction.response.send_message(f"🛑 Подписка удалена: '{query}'.", ephemeral=False)
		else:
			await interaction.response.send_message(f"❌ Подписка не найдена: '{query}'.", ephemeral=True)

	@app_commands.command(name="live-stop-all", description="Остановить все лайв-подписки для этого канала")
	async def live_stop_all(self, interaction: discord.Interaction) -> None:
		count = self.bot.subscription_store.clear_channel(interaction.channel_id)
		if count:
			await interaction.response.send_message(f"🧹 Удалено подписок: {count}.", ephemeral=False)
		else:
			await interaction.response.send_message("В этом канале нет активных подписок.", ephemeral=True)

	@app_commands.command(name="live-list", description="Показать список текущих лайв-подписок для этого канала")
	async def live_list(self, interaction: discord.Interaction) -> None:
		subs = self.bot.subscription_store.get_subscriptions(interaction.channel_id)
		if not subs:
			await interaction.response.send_message("Подписок нет.", ephemeral=True)
			return
		formatted = "\n".join(f"• {s}" for s in subs)
		await interaction.response.send_message(f"Текущие подписки:\n{formatted}", ephemeral=False)

	@app_commands.command(name="live-upcoming", description="Показать ближайшие матчи для подписок этого канала")
	async def live_upcoming(self, interaction: discord.Interaction) -> None:
		keys = self.bot.subscription_store.get_subscriptions(interaction.channel_id)
		items = await self.bot.football.get_upcoming_for_keys(keys)
		if not items:
			await interaction.response.send_message("Нет данных о ближайших матчах.", ephemeral=True)
			return
		await interaction.response.send_message("\n".join(items), ephemeral=False)

	@app_commands.command(name="live-now", description="Показать матчи, которые идут прямо сейчас")
	async def live_now(self, interaction: discord.Interaction) -> None:
		items = await self.bot.football.get_now_live()
		if not items:
			await interaction.response.send_message("Сейчас нет лайв-матчей.", ephemeral=True)
			return
		await interaction.response.send_message("\n".join(items), ephemeral=False)


async def setup(bot: commands.Bot) -> None:
	await bot.add_cog(LiveCog(bot))