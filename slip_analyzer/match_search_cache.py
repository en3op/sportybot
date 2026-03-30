"""
Match Search Cache
==================
SQLite cache for DuckDuckGo search results.
TTL: 6 hours (form data changes slowly)
"""

import sqlite3
import json
import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_DB = "search_cache.db"
CACHE_TTL_HOURS = 6


class MatchSearchCache:
    """SQLite cache for match search results with 6-hour TTL."""
    
    def __init__(self, db_path: str = None):
        self.db_path = db_path or CACHE_DB
        self._init_db()
    
    def _init_db(self):
        """Initialize cache database."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS search_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                match_key TEXT UNIQUE NOT NULL,
                home_team TEXT NOT NULL,
                away_team TEXT NOT NULL,
                league TEXT,
                tier TEXT,
                form_home TEXT,
                form_away TEXT,
                position_home INTEGER,
                position_away INTEGER,
                goals_home REAL,
                goals_away REAL,
                search_context TEXT,
                analysis_summary TEXT,
                verdict TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                expires_at TIMESTAMP NOT NULL
            )
        ''')
        c.execute('CREATE INDEX IF NOT EXISTS idx_match_key ON search_cache(match_key)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_expires ON search_cache(expires_at)')
        conn.commit()
        conn.close()
        logger.info(f"Search cache initialized: {self.db_path}")
    
    def _make_key(self, home: str, away: str) -> str:
        """Create normalized cache key."""
        h = home.lower().strip()
        a = away.lower().strip()
        return f"{h}|{a}"
    
    def get(self, home: str, away: str) -> Optional[dict]:
        """Get cached search result if not expired."""
        key = self._make_key(home, away)
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            SELECT home_team, away_team, league, tier, form_home, form_away,
                   position_home, position_away, goals_home, goals_away,
                   search_context, analysis_summary, verdict
            FROM search_cache 
            WHERE match_key = ? AND expires_at > ?
        ''', (key, datetime.now().isoformat()))
        
        row = c.fetchone()
        conn.close()
        
        if row:
            logger.info(f"Cache HIT: {home} vs {away}")
            return {
                "home_team": row[0],
                "away_team": row[1],
                "league": row[2],
                "tier": row[3] or "C",
                "form_home": row[4] or "",
                "form_away": row[5] or "",
                "position_home": row[6] or 0,
                "position_away": row[7] or 0,
                "goals_home": row[8] or 0.0,
                "goals_away": row[9] or 0.0,
                "search_context": row[10] or "",
                "analysis_summary": row[11] or "",
                "verdict": row[12] or "RISKY",
                "source": "cache"
            }
        
        logger.info(f"Cache MISS: {home} vs {away}")
        return None
    
    def set(self, home: str, away: str, data: dict):
        """Store search result with 6-hour TTL."""
        key = self._make_key(home, away)
        now = datetime.now()
        expires = now + timedelta(hours=CACHE_TTL_HOURS)
        
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('''
            INSERT OR REPLACE INTO search_cache 
            (match_key, home_team, away_team, league, tier, form_home, form_away,
             position_home, position_away, goals_home, goals_away,
             search_context, analysis_summary, verdict, created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            key,
            data.get("home_team", home),
            data.get("away_team", away),
            data.get("league", ""),
            data.get("tier", "C"),
            data.get("form_home", ""),
            data.get("form_away", ""),
            data.get("position_home", 0),
            data.get("position_away", 0),
            data.get("goals_home", 0.0),
            data.get("goals_away", 0.0),
            data.get("search_context", ""),
            data.get("analysis_summary", ""),
            data.get("verdict", "RISKY"),
            now.isoformat(),
            expires.isoformat()
        ))
        
        conn.commit()
        conn.close()
        logger.info(f"Cache SET: {home} vs {away} (expires: {expires})")
    
    def cleanup(self):
        """Remove expired entries."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute('DELETE FROM search_cache WHERE expires_at < ?', (datetime.now().isoformat(),))
        deleted = c.rowcount
        conn.commit()
        conn.close()
        if deleted > 0:
            logger.info(f"Cache cleanup: removed {deleted} expired entries")
        return deleted
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        
        c.execute('SELECT COUNT(*) FROM search_cache')
        total = c.fetchone()[0]
        
        c.execute('SELECT COUNT(*) FROM search_cache WHERE expires_at > ?', (datetime.now().isoformat(),))
        valid = c.fetchone()[0]
        
        conn.close()
        
        return {
            "total_entries": total,
            "valid_entries": valid,
            "expired_entries": total - valid
        }


# Global cache instance
_cache_instance = None

def get_cache() -> MatchSearchCache:
    """Get global cache instance."""
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = MatchSearchCache()
    return _cache_instance
