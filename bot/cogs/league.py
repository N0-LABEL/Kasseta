import discord
from discord import app_commands
from discord.ext import commands


class LeagueCog(commands.Cog):
	def __init__(self, bot: commands.Bot) -> None:
		self.bot = bot

	@app_commands.describe(league_name="Название лиги")
	@app_commands.command(name="league-table", description="Показать таблицу (турнирную таблицу) выбранной лиги")
	async def league_table(self, interaction: discord.Interaction, league_name: str) -> None:
		text = await self.bot.football.get_league_table(league_name)
		await interaction.response.send_message(text, ephemeral=False)

	@app_commands.describe(league_name="Название лиги")
	@app_commands.command(name="league-streaks", description="Показать серии (стрики) для выбранной лиги")
	async def league_streaks(self, interaction: discord.Interaction, league_name: str) -> None:
		text = await self.bot.football.get_league_streaks(league_name)
		await interaction.response.send_message(text, ephemeral=False)


async def setup(bot: commands.Bot) -> None:
	await bot.add_cog(LeagueCog(bot))