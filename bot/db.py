from __future__ import annotations

import os
import aiosqlite
from pathlib import Path
from typing import List, Optional, Dict, Any


class Database:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @classmethod
    async def create(cls, path: str) -> "Database":
        # Ensure parent directory exists for cross-platform use
        db_path = Path(path)
        if db_path.parent and not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(str(db_path))
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS subscriptions (
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                UNIQUE(user_id, subject)
            );
            """
        )
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS matches_state (
                match_id TEXT PRIMARY KEY,
                league TEXT,
                home TEXT,
                away TEXT,
                status TEXT,
                home_goals INTEGER,
                away_goals INTEGER,
                last_update INTEGER
            );
            """
        )
        await conn.commit()
        return cls(conn)

    async def add_subscription(self, user_id: int, subject: str) -> None:
        async with self._conn.execute(
            "INSERT OR IGNORE INTO subscriptions(user_id, subject) VALUES (?, ?)",
            (user_id, subject.strip()),
        ):
            await self._conn.commit()

    async def remove_subscription(self, user_id: int, subject: str) -> bool:
        cur = await self._conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ? AND subject = ?",
            (user_id, subject.strip()),
        )
        await self._conn.commit()
        return cur.rowcount > 0

    async def clear_subscriptions(self, user_id: int) -> int:
        cur = await self._conn.execute(
            "DELETE FROM subscriptions WHERE user_id = ?",
            (user_id,),
        )
        await self._conn.commit()
        return cur.rowcount or 0

    async def list_subscriptions(self, user_id: int) -> List[str]:
        cur = await self._conn.execute(
            "SELECT subject FROM subscriptions WHERE user_id = ? ORDER BY subject",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [r[0] for r in rows]

    async def upsert_match_state(self, match: Dict[str, Any]) -> None:
        await self._conn.execute(
            """
            INSERT INTO matches_state(match_id, league, home, away, status, home_goals, away_goals, last_update)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                league=excluded.league,
                home=excluded.home,
                away=excluded.away,
                status=excluded.status,
                home_goals=excluded.home_goals,
                away_goals=excluded.away_goals,
                last_update=excluded.last_update
            """,
            (
                match["id"],
                match.get("league"),
                match.get("home"),
                match.get("away"),
                match.get("status"),
                match.get("home_goals", 0),
                match.get("away_goals", 0),
                match.get("last_update", 0),
            ),
        )
        await self._conn.commit()

    async def get_match_state(self, match_id: str) -> Optional[Dict[str, Any]]:
        cur = await self._conn.execute(
            "SELECT match_id, league, home, away, status, home_goals, away_goals, last_update FROM matches_state WHERE match_id = ?",
            (match_id,),
        )
        row = await cur.fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "league": row[1],
            "home": row[2],
            "away": row[3],
            "status": row[4],
            "home_goals": row[5],
            "away_goals": row[6],
            "last_update": row[7],
        }

    async def remove_match_state(self, match_id: str) -> None:
        await self._conn.execute("DELETE FROM matches_state WHERE match_id = ?", (match_id,))
        await self._conn.commit()