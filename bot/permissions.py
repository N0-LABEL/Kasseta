import discord
from .config import BotConfig
from .embeds import Embeds


class CommandRejected(Exception):
    pass


async def require_guild_and_channel(interaction: discord.Interaction, config: BotConfig) -> None:
    if interaction.guild is None or interaction.guild_id != config.guild_id:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=Embeds.error("Команды доступны только на сервере."), ephemeral=True)
        raise CommandRejected("Wrong guild or DM")
    if interaction.channel is None or interaction.channel.id != config.commands_text_channel_id:
        if not interaction.response.is_done():
            await interaction.response.send_message(embed=Embeds.error("Команды можно использовать только в разрешённом канале."), ephemeral=True)
        raise CommandRejected("Wrong channel")