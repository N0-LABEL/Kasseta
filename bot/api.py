from __future__ import annotations

import time
from typing import List, Dict, Any, Tuple


class FootballAPI:
    def __init__(self, provider: str = "mock", api_key: str | None = None) -> None:
        self.provider = provider
        self.api_key = api_key
        # Demo data for mock
        self._mock_matches: Dict[str, Dict[str, Any]] = {
            "m1": {"id": "m1", "league": "Премьер-Лига", "home": "Зенит", "away": "Спартак", "status": "NS", "home_goals": 0, "away_goals": 0, "kickoff": time.time() + 600, "last_update": int(time.time())},
            "m2": {"id": "m2", "league": "Ла Лига", "home": "Барселона", "away": "Реал", "status": "1H", "home_goals": 1, "away_goals": 0, "kickoff": time.time() - 1200, "last_update": int(time.time())},
        }

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
        # Mock league table
        return [
            {"pos": 1, "team": "Команда A", "points": 45, "w": 14, "d": 3, "l": 2},
            {"pos": 2, "team": "Команда B", "points": 41, "w": 13, "d": 2, "l": 4},
        ]

    async def get_league_streaks(self, league: str) -> List[Dict[str, Any]]:
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

    def _match_matches_subjects(self, m: Dict[str, Any], subjects: List[str]) -> bool:
        if not subjects:
            return False
        sset = {s.lower() for s in subjects}
        return (
            m["league"].lower() in sset
            or m["home"].lower() in sset
            or m["away"].lower() in sset
        )