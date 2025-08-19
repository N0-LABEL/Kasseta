from __future__ import annotations

import discord
from typing import List, Dict, Any


COLOR_PRIMARY = 0x2B6CB0
COLOR_SUCCESS = 0x2F855A
COLOR_INFO = 0x3182CE
COLOR_WARNING = 0xD69E2E
COLOR_DANGER = 0xC53030


class Embeds:
    @staticmethod
    def help() -> discord.Embed:
        embed = discord.Embed(title="Помощь", color=COLOR_PRIMARY, description=(
            "Команды:\n"
            "/help — Показать это сообщение\n"
            "/live [команда|лига] — Подписаться на лайв\n"
            "/live-stop [команда|лига] — Отменить подписку\n"
            "/live-stop-all — Отменить все ваши подписки\n"
            "/live-list — Показать ваши подписки\n"
            "/live-upcoming — Ближайшие матчи\n"
            "/live-now — Матчи в эфире\n"
            "/league-table [лига] — Таблица лиги\n"
            "/league-streaks [лига] — Серии лиги\n"
        ))
        embed.set_footer(text="Все сообщения дублируются в указанный канал. Команды доступны только на сервере и только в разрешённом канале.")
        return embed

    @staticmethod
    def success(text: str) -> discord.Embed:
        return discord.Embed(description=text, color=COLOR_SUCCESS)

    @staticmethod
    def info(text: str) -> discord.Embed:
        return discord.Embed(description=text, color=COLOR_INFO)

    @staticmethod
    def error(text: str) -> discord.Embed:
        return discord.Embed(description=text, color=COLOR_DANGER)

    @staticmethod
    def subscriptions(subs: List[str], active_matches: List[Dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(title="Ваши подписки", color=COLOR_PRIMARY)
        if subs:
            embed.add_field(name="Предметы подписки", value="\n".join(f"• {s}" for s in subs), inline=False)
        else:
            embed.add_field(name="Предметы подписки", value="Нет активных подписок", inline=False)
        if active_matches:
            lines = []
            for m in active_matches:
                status = m.get("status")
                line = f"{m['league']} — {m['home']} {m['home_goals']}-{m['away_goals']} {m['away']} ({status})"
                lines.append(line)
            embed.add_field(name="Текущие матчи", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="Текущие матчи", value="Сейчас нет активных матчей по вашим подпискам", inline=False)
        return embed

    @staticmethod
    def matches_list(title: str, matches: List[Dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(title=title, color=COLOR_PRIMARY)
        if not matches:
            embed.description = "Ничего не найдено"
            return embed
        for m in matches:
            status = m.get("status")
            name = f"{m['league']}: {m['home']} vs {m['away']}"
            value = f"Счёт: {m['home_goals']}-{m['away_goals']} | Статус: {status}"
            embed.add_field(name=name, value=value, inline=False)
        return embed

    @staticmethod
    def league_table(league: str, table_rows: List[Dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(title=f"Таблица лиги: {league}", color=COLOR_PRIMARY)
        if not table_rows:
            embed.description = "Данные недоступны"
            return embed
        lines = []
        for r in table_rows:
            lines.append(f"{r['pos']}. {r['team']} — {r['points']} очков (W{r['w']}-D{r['d']}-L{r['l']})")
        embed.description = "\n".join(lines)
        return embed

    @staticmethod
    def league_streaks(league: str, streaks: List[Dict[str, Any]]) -> discord.Embed:
        embed = discord.Embed(title=f"Серии лиги: {league}", color=COLOR_PRIMARY)
        if not streaks:
            embed.description = "Данные недоступны"
            return embed
        lines = []
        for s in streaks:
            lines.append(f"{s['team']}: {s['type']} — {s['value']}")
        embed.description = "\n".join(lines)
        return embed

    @staticmethod
    def goal(match: Dict[str, Any]) -> discord.Embed:
        title = "ГОЛ!"
        desc = f"{match['league']} — {match['home']} {match['home_goals']}-{match['away_goals']} {match['away']}"
        return discord.Embed(title=title, description=desc, color=COLOR_WARNING)

    @staticmethod
    def match_end(match: Dict[str, Any]) -> discord.Embed:
        title = "Матч окончен"
        desc = f"{match['league']} — {match['home']} {match['home_goals']}-{match['away_goals']} {match['away']}"
        return discord.Embed(title=title, description=desc, color=COLOR_PRIMARY)