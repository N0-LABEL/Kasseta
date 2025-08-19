from __future__ import annotations

import logging
from typing import List, Dict, Any, Tuple, Optional, Set

import aiohttp


logger = logging.getLogger("api")

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

# Preferred country for ambiguous league names
PREFERRED_COUNTRY: Dict[str, str] = {
    "Premier League": "England",
    "La Liga": "Spain",
    "Bundesliga": "Germany",
    "Serie A": "Italy",
    "Ligue 1": "France",
    "Eredivisie": "Netherlands",
    "Primeira Liga": "Portugal",
    "Süper Lig": "Turkey",
}


def _contains_cyrillic(text: str) -> bool:
    return any('А' <= ch <= 'я' or ch == 'ё' or ch == 'Ё' for ch in (text or ""))


class FootballAPI:
    def __init__(self, provider: str = "mock", api_key: str | None = None) -> None:
        self.provider = provider
        self.api_key = api_key

    # ===== Public API =====
    async def get_live_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        if not (self.provider == "api_football" and self.api_key):
            return []
        norm_subjects = await self._normalize_subjects(subjects)
        fixtures = await self._af_fetch_live()
        return [self._to_match_dict(f) for f in fixtures if self._fixture_matches_subjects(f, norm_subjects)]

    async def get_upcoming_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        if not (self.provider == "api_football" and self.api_key):
            return []
        norm_subjects = await self._normalize_subjects(subjects)
        matches: List[Dict[str, Any]] = []
        # Resolve leagues and teams
        league_ids = await self._af_resolve_league_ids(list(norm_subjects))
        team_ids = await self._af_resolve_team_ids(list(norm_subjects))
        # Fetch upcoming per league
        for league_id, season in league_ids:
            fixtures = await self._af_fetch_upcoming_by_league(league_id, season, limit=10)
            for f in fixtures:
                if self._fixture_matches_subjects(f, norm_subjects):
                    matches.append(self._to_match_dict(f))
        # Fetch upcoming per team
        for team_id in team_ids:
            fixtures = await self._af_fetch_upcoming_by_team(team_id, limit=10)
            for f in fixtures:
                if self._fixture_matches_subjects(f, norm_subjects):
                    matches.append(self._to_match_dict(f))
        # De-dup by id
        seen: Set[int] = set()
        unique = []
        for m in matches:
            mid = m.get("id")
            if mid in seen:
                continue
            seen.add(mid)
            unique.append(m)
        return unique

    async def get_active_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # Treat active as live for now
        return await self.get_live_for_user(user_id, subjects)

    async def get_league_table(self, league: str) -> List[Dict[str, Any]]:
        if self.provider == "api_football" and self.api_key:
            table = await self._af_get_league_table(league)
            return table or []
        return []

    async def get_league_streaks(self, league: str) -> List[Dict[str, Any]]:
        # Compute from standings form if available
        rows = await self._af_get_league_table(league)
        if not rows:
            return []
        streaks: List[Dict[str, Any]] = []
        for r in rows:
            form: Optional[str] = r.get("form")
            if not form:
                continue
            # Normalize form like "WWDLW" or "W,W,D,L,W" into sequence of last->first
            seq = form.replace(",", "").strip().upper()
            if not seq:
                continue
            # Assume rightmost is most recent (API-FOOTBALL convention)
            current = seq[-1]
            length = 1
            for ch in reversed(seq[:-1]):
                if ch == current:
                    length += 1
                else:
                    break
            if current == 'W':
                stype = "Победная серия"
            elif current == 'D':
                stype = "Серия ничьих"
            else:
                stype = "Серия поражений"
            streaks.append({"team": r["team"], "type": stype, "value": length})
        streaks.sort(key=lambda s: s["value"], reverse=True)
        return streaks[:10]

    async def poll_changes(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Not implemented without a push/long-poll plan; scheduler can poll live fixtures periodically and diff
        return [], []

    async def get_subject_suggestions(self, prefix: str, limit: int = 20) -> List[str]:
        if not (self.provider == "api_football" and self.api_key):
            return []
        query = prefix or ""
        if _contains_cyrillic(query):
            mapped = RU_EN_SYNONYMS_TEAMS.get(query.lower().strip()) or await self._ru_to_en(query)
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
            mapped = RU_EN_SYNONYMS_LEAGUES.get(query.lower().strip()) or await self._ru_to_en(query)
            query = mapped or query
        return await self._af_search_leagues(query, limit)

    async def get_next_for_subject(self, subject: str) -> List[Dict[str, Any]]:
        """If subject is a team -> return 1 next match; if league -> up to 5 next matches."""
        if not (self.provider == "api_football" and self.api_key):
            return []
        name = subject or ""
        if _contains_cyrillic(name):
            name = RU_EN_SYNONYMS_TEAMS.get(name.lower().strip()) or RU_EN_SYNONYMS_LEAGUES.get(name.lower().strip()) or await self._ru_to_en(name) or name
        # Prefer team match if both exist
        team_id = await self._af_search_team_id(name)
        if team_id:
            fixtures = await self._af_fetch_upcoming_by_team(team_id, limit=1)
            return [self._to_match_dict(f) for f in fixtures]
        # else try league
        league_info = await self._af_resolve_league(name)
        if league_info:
            lid = (league_info.get("league") or {}).get("id")
            season = await self._af_get_current_season(league_info)
            if lid and season:
                fixtures = await self._af_fetch_upcoming_by_league(lid, season, limit=5)
                return [self._to_match_dict(f) for f in fixtures]
        return []

    # ===== Helpers (API-FOOTBALL) =====
    async def _af_request(self, path: str, params: Dict[str, Any]) -> Any:
        url = f"https://v3.football.api-sports.io{path}"
        headers = {"x-apisports-key": self.api_key}
        try:
            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(url, params=params, timeout=15) as resp:
                    status = resp.status
                    if status >= 400:
                        text = await resp.text()
                        logger.error("API error %s %s: %s", status, url, text)
                    resp.raise_for_status()
                    return await resp.json()
        except Exception as e:
            logger.exception("HTTP request failed: %s %s %s", url, params, e)
            raise

    async def _af_search_leagues(self, query: str, limit: int) -> List[str]:
        try:
            data = await self._af_request("/leagues", {"search": query or ""})
            names: List[str] = []
            for item in data.get("response", [])[: max(limit, 1) * 3]:
                league = item.get("league") or {}
                country = (item.get("country") or {}).get("name")
                name = league.get("name")
                if not name:
                    continue
                # Prefer with country disambiguation
                pref = PREFERRED_COUNTRY.get(name)
                if pref and country and country != pref:
                    continue
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
            for item in data.get("response", [])[: max(limit, 1) * 3]:
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
        except Exception as e:
            logger.warning("RU→EN mapping failed for '%s': %s", text, e)
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
        # Prefer preferred country match
        pref_country = PREFERRED_COUNTRY.get(name_q)
        if pref_country:
            filtered = [c for c in candidates if (c.get("country") or {}).get("name") == pref_country]
            if filtered:
                candidates = filtered
        # Prefer exact case-insensitive match
        name_l = (name_q or "").strip().lower()
        candidates.sort(key=lambda it: 0 if (it.get("league", {}).get("name", "").lower() == name_l) else 1)
        return candidates[0]

    async def _af_get_current_season(self, league_info: Dict[str, Any]) -> Optional[int]:
        seasons = league_info.get("seasons", [])
        for s in seasons:
            if s.get("current"):
                return s.get("year")
        return seasons[-1].get("year") if seasons else None

    async def _af_get_league_table(self, league_name: str) -> List[Dict[str, Any]] | None:
        try:
            league_info = await self._af_resolve_league(league_name)
            if not league_info:
                logger.info("League not found: %s", league_name)
                return None
            league = league_info.get("league", {})
            league_id = league.get("id")
            current_season = await self._af_get_current_season(league_info)
            if not league_id or not current_season:
                logger.info("No league id/season for: %s", league_name)
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
                form = row.get("form")  # e.g., "WWDLW"
                if team_name and rank is not None and points is not None:
                    rows.append({"pos": rank, "team": team_name, "points": points, "w": w, "d": d, "l": l, "form": form})
            rows.sort(key=lambda r: r["pos"])  # ensure order
            return rows
        except Exception as e:
            logger.exception("Failed to fetch standings for '%s': %s", league_name, e)
            return None

    async def _af_search_team_id(self, name: str) -> Optional[int]:
        data = await self._af_request("/teams", {"search": name})
        resp = data.get("response", [])
        if not resp:
            return None
        # Prefer exact match
        name_l = name.lower().strip()
        resp.sort(key=lambda it: 0 if (it.get("team", {}).get("name", "").lower() == name_l) else 1)
        return resp[0].get("team", {}).get("id")

    async def _af_resolve_team_ids(self, subjects: List[str]) -> Set[int]:
        ids: Set[int] = set()
        for s in subjects:
            tid = await self._af_search_team_id(s)
            if tid:
                ids.add(tid)
        return ids

    async def _af_resolve_league_ids(self, subjects: List[str]) -> Set[Tuple[int, int]]:
        ids: Set[Tuple[int, int]] = set()
        for s in subjects:
            info = await self._af_resolve_league(s)
            if info:
                lid = (info.get("league") or {}).get("id")
                season = await self._af_get_current_season(info)
                if lid and season:
                    ids.add((lid, season))
        return ids

    async def _af_fetch_live(self) -> List[Dict[str, Any]]:
        try:
            data = await self._af_request("/fixtures", {"live": "all"})
            return data.get("response", [])
        except Exception as e:
            logger.exception("Failed to fetch live fixtures: %s", e)
            return []

    async def _af_fetch_upcoming_by_league(self, league_id: int, season: int, limit: int) -> List[Dict[str, Any]]:
        try:
            data = await self._af_request("/fixtures", {"league": league_id, "season": season, "next": limit})
            return data.get("response", [])
        except Exception:
            return []

    async def _af_fetch_upcoming_by_team(self, team_id: int, limit: int) -> List[Dict[str, Any]]:
        try:
            data = await self._af_request("/fixtures", {"team": team_id, "next": limit})
            return data.get("response", [])
        except Exception:
            return []

    async def _normalize_subjects(self, subjects: List[str]) -> Set[str]:
        out: Set[str] = set()
        for s in subjects or []:
            q = s
            if _contains_cyrillic(q):
                q = RU_EN_SYNONYMS_TEAMS.get(q.lower().strip()) or RU_EN_SYNONYMS_LEAGUES.get(q.lower().strip()) or await self._ru_to_en(q) or q
            out.add(q.strip())
        return {x for x in out if x}

    def _fixture_matches_subjects(self, fixture: Dict[str, Any], subjects: Set[str]) -> bool:
        try:
            league_name = (fixture.get("league") or {}).get("name", "")
            home = (fixture.get("teams") or {}).get("home", {}).get("name", "")
            away = (fixture.get("teams") or {}).get("away", {}).get("name", "")
            names = {league_name.lower(), home.lower(), away.lower()}
            subs = {s.lower() for s in subjects}
            return bool(names & subs)
        except Exception:
            return False

    def _to_match_dict(self, fixture: Dict[str, Any]) -> Dict[str, Any]:
        ts = (fixture.get("fixture") or {}).get("timestamp")  # seconds UTC
        return {
            "id": fixture.get("fixture", {}).get("id"),
            "league": (fixture.get("league") or {}).get("name"),
            "home": (fixture.get("teams") or {}).get("home", {}).get("name"),
            "away": (fixture.get("teams") or {}).get("away", {}).get("name"),
            "status": (fixture.get("fixture") or {}).get("status", {}).get("short"),
            "home_goals": (fixture.get("goals") or {}).get("home", 0),
            "away_goals": (fixture.get("goals") or {}).get("away", 0),
            "ts": ts,
        }