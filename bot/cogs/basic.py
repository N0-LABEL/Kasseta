import discord
from discord import app_commands
from discord.ext import commands


HELP_TEXT = (
	"/help — Показать это сообщение\n"
	"/live [команда-или-лига] — Отправлять лайв-счёты в этот канал\n"
	"/live-stop [команда-или-лига] — Остановить лайв для указанной подписки\n"
	"/live-stop-all — Остановить все лайв-подписки для канала\n"
	"/live-list — Показать список текущих подписок канала\n"
	"/live-upcoming — Показать ближайшие матчи по подпискам\n"
	"/live-now — Показать матчи, идущие сейчас\n"
	"/league-table [лига] — Показать турнирную таблицу лиги\n"
	"/league-streaks [лига] — Показать серии (стрики) по лиге"
)


class BasicCog(commands.Cog):
	def __init__(self, bot: commands.Bot) -> None:
		self.bot = bot

	@app_commands.command(name="help", description="Показать список команд")
	async def help_command(self, interaction: discord.Interaction) -> None:
		await interaction.response.send_message(HELP_TEXT, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
	await bot.add_cog(BasicCog(bot))