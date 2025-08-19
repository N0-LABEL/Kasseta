from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple

import aiohttp


# Basic RU→EN synonyms (extendable)
RU_EN_SYNONYMS_TEAMS: Dict[str, str] = {
    "бавария": "Bayern Munich",
    "бавария мюнхен": "Bayern Munich",
    "реал": "Real Madrid",
    "реал мадрид": "Real Madrid",
    "барселона": "Barcelona",
    "атлетико": "Atletico Madrid",
    "манчестер сити": "Manchester City",
    "манчестер юнайтед": "Manchester United",
    "ливерпуль": "Liverpool",
    "арсенал": "Arsenal",
    "челси": "Chelsea",
    "тоттенхэм": "Tottenham",
    "псж": "Paris Saint Germain",
    "пари сен-жермен": "Paris Saint Germain",
    "ювентус": "Juventus",
    "интер": "Inter",
    "интер милан": "Inter",
    "милан": "AC Milan",
    "наполі": "Napoli",
    "зенит": "Zenit",
    "спартак": "Spartak Moscow",
    "локомотив": "Lokomotiv Moscow",
    "цска": "CSKA Moscow",
}

RU_EN_SYNONYMS_LEAGUES: Dict[str, str] = {
    "премьер-лига": "Premier League",
    "апл": "Premier League",
    "ла лига": "La Liga",
    "сегунда": "La Liga 2",
    "серия а": "Serie A",
    "бундеслига": "Bundesliga",
    "лига 1": "Ligue 1",
}


def _contains_cyrillic(text: str) -> bool:
    return any('А' <= ch <= 'я' or ch == 'ё' or ch == 'Ё' for ch in text)


class FootballAPI:
    def __init__(self, provider: str = "mock", api_key: str | None = None) -> None:
        self.provider = provider
        self.api_key = api_key

    # ===== Public API =====
    async def get_live_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # TODO: implement with real provider
        return []

    async def get_upcoming_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # TODO: implement with real provider
        return []

    async def get_active_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # TODO: implement with real provider
        return []

    async def get_league_table(self, league: str) -> List[Dict[str, Any]]:
        if self.provider == "api_football" and self.api_key:
            table = await self._af_get_league_table(league)
            return table or []
        return []

    async def get_league_streaks(self, league: str) -> List[Dict[str, Any]]:
        # TODO: implement with real provider
        return []

    async def poll_changes(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # TODO: implement with real provider
        return [], []

    async def get_subject_suggestions(self, prefix: str, limit: int = 20) -> List[str]:
        if not (self.provider == "api_football" and self.api_key):
            return []
        query = prefix or ""
        if _contains_cyrillic(query):
            # Try synonyms quick map, then Wikipedia RU→EN
            mapped = RU_EN_SYNONYMS_TEAMS.get(query.lower().strip())
            if not mapped:
                mapped = await self._ru_to_en(query)
            query = mapped or query
        leagues = await self._af_search_leagues(query, limit)
        teams = await self._af_search_teams(query, limit)
        out: List[str] = []
        seen = set()
        for s in leagues + teams:
            if s not in seen:
                seen.add(s)
                out.append(s)
            if len(out) >= limit:
                break
        return out

    async def get_league_suggestions(self, prefix: str, limit: int = 20) -> List[str]:
        if not (self.provider == "api_football" and self.api_key):
            return []
        query = prefix or ""
        if _contains_cyrillic(query):
            mapped = RU_EN_SYNONYMS_LEAGUES.get(query.lower().strip())
            if not mapped:
                mapped = await self._ru_to_en(query)
            query = mapped or query
        return await self._af_search_leagues(query, limit)

    # ===== Helpers (API-FOOTBALL) =====
    async def _af_request(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"https://v3.football.api-sports.io{path}"
        headers = {"x-apisports-key": self.api_key}
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.get(url, params=params, timeout=15) as resp:
                resp.raise_for_status()
                return await resp.json()

    async def _af_search_leagues(self, query: str, limit: int) -> List[str]:
        try:
            data = await self._af_request("/leagues", {"search": query or ""})
            names: List[str] = []
            for item in data.get("response", [])[: max(limit, 1) * 2]:
                league = item.get("league") or {}
                name = league.get("name")
                if name:
                    names.append(name)
            # unique, keep order
            seen = set()
            result: List[str] = []
            for n in names:
                if n not in seen:
                    seen.add(n)
                    result.append(n)
                if len(result) >= limit:
                    break
            return result
        except Exception:
            return []

    async def _af_search_teams(self, query: str, limit: int) -> List[str]:
        try:
            data = await self._af_request("/teams", {"search": query or ""})
            names: List[str] = []
            for item in data.get("response", [])[: max(limit, 1) * 2]:
                team = item.get("team") or {}
                name = team.get("name")
                if name:
                    names.append(name)
            # unique, keep order
            seen = set()
            result: List[str] = []
            for n in names:
                if n not in seen:
                    seen.add(n)
                    result.append(n)
                if len(result) >= limit:
                    break
            return result
        except Exception:
            return []

    async def _ru_to_en(self, text: str) -> str | None:
        # Use Russian Wikipedia to resolve English interlanguage link
        try:
            async with aiohttp.ClientSession() as session:
                # Search best RU page
                search_url = "https://ru.wikipedia.org/w/api.php"
                params = {"action": "query", "list": "search", "srsearch": text, "srlimit": 1, "format": "json"}
                async with session.get(search_url, params=params, timeout=10) as resp:
                    data = await resp.json()
                hits = data.get("query", {}).get("search", [])
                if not hits:
                    return None
                title = hits[0].get("title")
                if not title:
                    return None
                # Fetch English langlink
                info_params = {"action": "query", "prop": "langlinks", "titles": title, "lllang": "en", "format": "json"}
                async with session.get(search_url, params=info_params, timeout=10) as resp:
                    data2 = await resp.json()
                pages = data2.get("query", {}).get("pages", {})
                for _pid, page in pages.items():
                    links = page.get("langlinks", [])
                    if links:
                        return links[0].get("*")
                return None
        except Exception:
            return None

    async def _af_resolve_league(self, name: str) -> Dict[str, Any] | None:
        # Map RU league to EN via synonyms or Wikipedia
        name_q = name
        if _contains_cyrillic(name_q):
            name_q = RU_EN_SYNONYMS_LEAGUES.get(name_q.lower().strip()) or await self._ru_to_en(name_q) or name_q
        data = await self._af_request("/leagues", {"search": name_q})
        candidates = data.get("response", [])
        if not candidates:
            return None
        # Prefer exact case-insensitive match
        name_l = (name_q or "").strip().lower()
        candidates.sort(key=lambda it: 0 if (it.get("league", {}).get("name", "").lower() == name_l) else 1)
        return candidates[0]

    async def _af_get_league_table(self, league_name: str) -> List[Dict[str, Any]] | None:
        try:
            league_info = await self._af_resolve_league(league_name)
            if not league_info:
                return None
            league = league_info.get("league", {})
            league_id = league.get("id")
            seasons = league_info.get("seasons", [])
            current_season = None
            for s in seasons:
                if s.get("current"):
                    current_season = s.get("year")
                    break
            if not league_id or not current_season:
                return None
            data = await self._af_request("/standings", {"league": league_id, "season": current_season})
            resp = data.get("response", [])
            if not resp:
                return None
            standings_groups = resp[0].get("league", {}).get("standings", [])
            if not standings_groups:
                return None
            rows: List[Dict[str, Any]] = []
            for row in standings_groups[0]:
                team_name = (row.get("team") or {}).get("name")
                rank = row.get("rank")
                points = row.get("points")
                all_stats = row.get("all") or {}
                w = (all_stats.get("win") or 0)
                d = (all_stats.get("draw") or 0)
                l = (all_stats.get("lose") or 0)
                if team_name and rank is not None and points is not None:
                    rows.append({"pos": rank, "team": team_name, "points": points, "w": w, "d": d, "l": l})
            rows.sort(key=lambda r: r["pos"])  # ensure order
            return rows
        except Exception:
            return None

    # ===== Utils =====
    def _match_matches_subjects(self, m: Dict[str, Any], subjects: List[str]) -> bool:
        # TODO: real matching
        return False