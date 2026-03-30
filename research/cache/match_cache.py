"""
Two-tier match data cache: L1 in-memory dict, L2 SQLite.

TTL strategy (seconds):
  live_odds      60     — changes every few seconds
  match_info    3600    — teams/league/time rarely change
  form         21600    — updates after each matchday
  h2h          21600    — historical, slow-moving
  injuries      7200    — updates before kickoff
  lineups       7200    — confirmed ~1h before kickoff
  historical   86400    — almost never changes

Usage:
    cache = MatchCache("cache.db")
    cache.set("odds:arsenal:chelsea", odds_dict, "live_odds")
    odds = cache.get("odds:arsenal:chelsea")  # returns dict or None
"""

import json
import sqlite3
import time
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default TTL per category (seconds)
TTL_DEFAULTS = {
    "live_odds": 60,
    "match_info": 3600,
    "form": 21600,
    "h2h": 21600,
    "injuries": 7200,
    "lineups": 7200,
    "historical": 86400,
    "default": 3600,
}


class MatchCache:
    """Two-tier cache: memory (L1) + SQLite (L2).

    Reads go memory-first. Writes hit both tiers.
    Expired entries are lazily evicted on read.
    """

    def __init__(self, db_path: str = "cache.db"):
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")  # faster writes
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                key       TEXT PRIMARY KEY,
                value     TEXT NOT NULL,
                category  TEXT NOT NULL DEFAULT 'default',
                expires_at REAL NOT NULL,
                created_at REAL NOT NULL
            )
        """)
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_cache_expires ON cache(expires_at)"
        )
        self.conn.commit()

        # L1: in-memory hot cache
        self._memory: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any:
        """Get cached value. Returns None on miss or expiry."""

        # L1 — memory
        if key in self._memory:
            expires, value = self._memory[key]
            if time.time() < expires:
                return value
            del self._memory[key]

        # L2 — SQLite
        row = self.conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()

        if row is None:
            return None

        if time.time() >= row[1]:
            # Expired — delete lazily
            self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self.conn.commit()
            return None

        try:
            value = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            return None

        # Promote to L1
        self._memory[key] = (row[1], value)
        return value

    def set(self, key: str, value: Any, category: str = "default"):
        """Store a value with automatic TTL based on category."""
        ttl = TTL_DEFAULTS.get(category, TTL_DEFAULTS["default"])
        expires = time.time() + ttl

        # L1
        self._memory[key] = (expires, value)

        # L2
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError):
            logger.warning(f"Cannot serialize cache key {key}")
            return

        self.conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, category, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (key, serialized, category, expires, time.time()),
        )
        self.conn.commit()

    def invalidate(self, key: str):
        """Force-expire a cache entry."""
        self._memory.pop(key, None)
        self.conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        self.conn.commit()

    def cleanup(self):
        """Purge all expired entries. Call periodically."""
        now = time.time()
        self.conn.execute("DELETE FROM cache WHERE expires_at < ?", (now,))
        self.conn.commit()

        # Clean L1
        expired = [k for k, (exp, _) in self._memory.items() if exp < now]
        for k in expired:
            del self._memory[k]

        if expired:
            logger.info(f"Cache cleanup: removed {len(expired)} expired entries")

    def stats(self) -> dict:
        """Return cache statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        expired = self.conn.execute(
            "SELECT COUNT(*) FROM cache WHERE expires_at < ?", (time.time(),)
        ).fetchone()[0]
        return {
            "l1_entries": len(self._memory),
            "l2_entries": total,
            "l2_expired": expired,
            "l2_active": total - expired,
        }
