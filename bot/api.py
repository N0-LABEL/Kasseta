from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple

import aiohttp


class FootballAPI:
    def __init__(self, provider: str = "mock", api_key: str | None = None) -> None:
        self.provider = provider
        self.api_key = api_key
        # Demo data for mock
        self._mock_matches: Dict[str, Dict[str, Any]] = {
            "m1": {"id": "m1", "league": "Премьер-Лига", "home": "Зенит", "away": "Спартак", "status": "NS", "home_goals": 0, "away_goals": 0, "kickoff": time.time() + 600, "last_update": int(time.time())},
            "m2": {"id": "m2", "league": "Ла Лига", "home": "Барселона", "away": "Реал", "status": "1H", "home_goals": 1, "away_goals": 0, "kickoff": time.time() - 1200, "last_update": int(time.time())},
        }

    # ===== Public API =====
    async def get_live_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # Mock: return matches whose league or team matches subjects and status is live
        result: List[Dict[str, Any]] = []
        for m in self._mock_matches.values():
            if m["status"] in {"1H", "HT", "2H", "ET"} and self._match_matches_subjects(m, subjects):
                result.append(m.copy())
        return result

    async def get_upcoming_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        now = time.time()
        for m in self._mock_matches.values():
            if m["status"] == "NS" and m.get("kickoff", 0) > now and self._match_matches_subjects(m, subjects):
                result.append(m.copy())
        return result

    async def get_active_for_user(self, user_id: int, subjects: List[str]) -> List[Dict[str, Any]]:
        # Active = not finished and matches subjects
        result: List[Dict[str, Any]] = []
        for m in self._mock_matches.values():
            if m["status"] not in {"FT", "AET", "PEN"} and self._match_matches_subjects(m, subjects):
                result.append(m.copy())
        return result

    async def get_league_table(self, league: str) -> List[Dict[str, Any]]:
        if self.provider == "api_football" and self.api_key:
            table = await self._af_get_league_table(league)
            if table is not None:
                return table
        # Fallback mock
        return [
            {"pos": 1, "team": "Команда A", "points": 45, "w": 14, "d": 3, "l": 2},
            {"pos": 2, "team": "Команда B", "points": 41, "w": 13, "d": 2, "l": 4},
        ]

    async def get_league_streaks(self, league: str) -> List[Dict[str, Any]]:
        # Placeholder: real API mapping не реализован; оставить mock
        return [
            {"team": "Команда A", "type": "Победная серия", "value": 5},
            {"team": "Команда C", "type": "Без побед", "value": 4},
        ]

    async def poll_changes(self) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        # Returns (goals, finished)
        goals: List[Dict[str, Any]] = []
        finished: List[Dict[str, Any]] = []
        # Mock: flip statuses randomly not implemented; keep static for demo
        return goals, finished

    async def get_subject_suggestions(self, prefix: str, limit: int = 20) -> List[str]:
        if self.provider == "api_football" and self.api_key:
            leagues = await self._af_search_leagues(prefix, limit)
            teams = await self._af_search_teams(prefix, limit)
            out: List[str] = []
            seen = set()
            for s in leagues + teams:
                if s not in seen:
                    seen.add(s)
                    out.append(s)
                if len(out) >= limit:
                    break
            return out
        # mock
        prefix_l = (prefix or "").lower()
        pool = set()
        for m in self._mock_matches.values():
            pool.add(m["league"]) 
            pool.add(m["home"]) 
            pool.add(m["away"]) 
        items = sorted(pool)
        if prefix_l:
            items = [x for x in items if x.lower().startswith(prefix_l)]
        return items[:limit]

    async def get_league_suggestions(self, prefix: str, limit: int = 20) -> List[str]:
        if self.provider == "api_football" and self.api_key:
            return await self._af_search_leagues(prefix, limit)
        prefix_l = (prefix or "").lower()
        leagues = sorted({m["league"] for m in self._mock_matches.values()})
        if prefix_l:
            leagues = [x for x in leagues if x.lower().startswith(prefix_l)]
        return leagues[:limit]

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

    async def _af_resolve_league(self, name: str) -> Dict[str, Any] | None:
        data = await self._af_request("/leagues", {"search": name})
        candidates = data.get("response", [])
        if not candidates:
            return None
        # Prefer exact case-insensitive match
        name_l = name.strip().lower()
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
        if not subjects:
            return False
        sset = {s.lower() for s in subjects}
        return (
            m["league"].lower() in sset
            or m["home"].lower() in sset
            or m["away"].lower() in sset
        )