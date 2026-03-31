"""
Prediction Pool Manager
========================
Handles prediction_pool.db schema and CRUD operations.
Stores 7-day lookahead predictions for football matches.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prediction_pool.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_pool_db():
    """Create prediction pool tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS matches (
            match_id TEXT PRIMARY KEY,
            league TEXT NOT NULL,
            match_date TEXT NOT NULL,
            home_team TEXT NOT NULL,
            away_team TEXT NOT NULL,
            status TEXT DEFAULT 'scheduled',
            source TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            expires_at TEXT
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            market TEXT NOT NULL,
            pick TEXT NOT NULL,
            odds REAL NOT NULL,
            confidence REAL NOT NULL,
            risk_tier TEXT NOT NULL,
            reasoning TEXT,
            model_version TEXT DEFAULT 'v2',
            source_data TEXT,
            result TEXT DEFAULT 'pending',
            graded_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );

        CREATE TABLE IF NOT EXISTS match_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL UNIQUE,
            home_form TEXT,
            away_form TEXT,
            home_goals_avg REAL DEFAULT 0,
            away_goals_avg REAL DEFAULT 0,
            home_conceded_avg REAL DEFAULT 0,
            away_conceded_avg REAL DEFAULT 0,
            home_position INTEGER DEFAULT 0,
            away_position INTEGER DEFAULT 0,
            h2h_home_wins INTEGER DEFAULT 0,
            h2h_draws INTEGER DEFAULT 0,
            h2h_away_wins INTEGER DEFAULT 0,
            xg_estimate REAL DEFAULT 0,
            motivation_factor TEXT,
            injury_impact TEXT,
            research_source TEXT,
            raw_data TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id)
        );

        CREATE TABLE IF NOT EXISTS user_slips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            username TEXT,
            slip_text TEXT,
            parsed_matches TEXT,
            returned_slips TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS grading_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_id TEXT NOT NULL,
            prediction_id INTEGER,
            actual_home_goals INTEGER,
            actual_away_goals INTEGER,
            actual_result TEXT,
            was_correct INTEGER DEFAULT 0,
            graded_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (match_id) REFERENCES matches(match_id),
            FOREIGN KEY (prediction_id) REFERENCES predictions(id)
        );

        CREATE TABLE IF NOT EXISTS accuracy_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            period TEXT NOT NULL,
            market TEXT,
            risk_tier TEXT,
            total INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            accuracy REAL DEFAULT 0,
            avg_confidence REAL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_matches_date ON matches(match_date);
        CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status);
        CREATE INDEX IF NOT EXISTS idx_matches_teams ON matches(home_team, away_team);
        CREATE INDEX IF NOT EXISTS idx_predictions_match ON predictions(match_id);
        CREATE INDEX IF NOT EXISTS idx_predictions_confidence ON predictions(confidence DESC);
        CREATE INDEX IF NOT EXISTS idx_predictions_tier ON predictions(risk_tier);
        CREATE INDEX IF NOT EXISTS idx_predictions_result ON predictions(result);
        CREATE INDEX IF NOT EXISTS idx_research_match ON match_research(match_id);
    """)
    conn.commit()
    conn.close()
    logger.info("Prediction pool database initialized")


# =============================================================================
# MATCH CRUD
# =============================================================================

def upsert_match(match_id: str, league: str, match_date: str, home: str, away: str,
                 source: str = "sportybet", status: str = "scheduled") -> None:
    """Insert or update a match in the pool."""
    conn = _get_db()
    expires = (datetime.fromisoformat(match_date) + timedelta(hours=4)).isoformat() if match_date else None
    conn.execute("""
        INSERT INTO matches (match_id, league, match_date, home_team, away_team, source, status, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            league=excluded.league, match_date=excluded.match_date,
            home_team=excluded.home_team, away_team=excluded.away_team,
            source=excluded.source, status=excluded.status, expires_at=excluded.expires_at
    """, (match_id, league, match_date, home, away, source, status, expires))
    conn.commit()
    conn.close()


def get_match(match_id: str) -> Optional[dict]:
    """Get a single match by ID."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM matches WHERE match_id = ?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_matches_by_date(start_date: str, end_date: str, status: str = None) -> list[dict]:
    """Get matches within a date range."""
    conn = _get_db()
    if status:
        rows = conn.execute(
            "SELECT * FROM matches WHERE match_date >= ? AND match_date <= ? AND status = ? ORDER BY match_date",
            (start_date, end_date, status)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM matches WHERE match_date >= ? AND match_date <= ? ORDER BY match_date",
            (start_date, end_date)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_active_matches() -> list[dict]:
    """Get all scheduled matches that haven't expired."""
    conn = _get_db()
    now = datetime.now().isoformat()
    rows = conn.execute(
        "SELECT * FROM matches WHERE status = 'scheduled' AND (expires_at IS NULL OR expires_at > ?) ORDER BY match_date",
        (now,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_today_matches() -> list[dict]:
    """Get matches scheduled for today."""
    conn = _get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM matches WHERE match_date >= ? AND match_date < ? AND status = 'scheduled' ORDER BY match_date",
        (today, tomorrow)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tomorrow_matches() -> list[dict]:
    """Get matches scheduled for tomorrow."""
    conn = _get_db()
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    day_after = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT * FROM matches WHERE match_date >= ? AND match_date < ? AND status = 'scheduled' ORDER BY match_date",
        (tomorrow, day_after)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_match_status(match_id: str, status: str):
    """Update a match's status (scheduled/live/finished/cancelled)."""
    conn = _get_db()
    conn.execute("UPDATE matches SET status = ? WHERE match_id = ?", (status, match_id))
    conn.commit()
    conn.close()


def purge_expired():
    """Remove matches that have expired (finished more than 24h ago).
    Protects matches with approved or manual predictions.
    """
    conn = _get_db()
    cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
    
    # Only delete matches where ALL predictions are non-approved and non-manual
    # OR matches with NO predictions at all.
    query = """
        DELETE FROM matches 
        WHERE expires_at < ? 
        AND match_id NOT IN (
            SELECT match_id FROM predictions 
            WHERE approved = 1 OR model_version = 'manual'
        )
    """
    deleted = conn.execute(query, (cutoff,)).rowcount
    conn.commit()
    conn.close()
    logger.info(f"Purged {deleted} expired matches")
    return deleted


# =============================================================================
# PREDICTION CRUD
# =============================================================================

def store_prediction(match_id: str, market: str, pick: str, odds: float,
                     confidence: float, risk_tier: str, reasoning: str = "",
                     source_data: dict = None) -> int:
    """Store a prediction. Returns prediction ID."""
    conn = _get_db()
    cursor = conn.execute("""
        INSERT INTO predictions (match_id, market, pick, odds, confidence, risk_tier, reasoning, source_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (match_id, market, pick, odds, confidence, risk_tier, reasoning,
          json.dumps(source_data) if source_data else None))
    pred_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return pred_id


def get_predictions_for_match(match_id: str) -> list[dict]:
    """Get all predictions for a match, sorted by confidence."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM predictions WHERE match_id = ? ORDER BY confidence DESC",
        (match_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_top_predictions(min_confidence: float = 70, max_results: int = 50) -> list[dict]:
    """Get top predictions across all active matches."""
    conn = _get_db()
    now = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT p.*, m.home_team, m.away_team, m.league, m.match_date
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.confidence >= ? AND p.result = 'pending'
          AND m.status = 'scheduled' AND (m.expires_at IS NULL OR m.expires_at > ?)
        ORDER BY p.confidence DESC
        LIMIT ?
    """, (min_confidence, now, max_results)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_predictions_by_tier(risk_tier: str, min_confidence: float = 60) -> list[dict]:
    """Get predictions filtered by risk tier."""
    conn = _get_db()
    now = datetime.now().isoformat()
    rows = conn.execute("""
        SELECT p.*, m.home_team, m.away_team, m.league, m.match_date
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.risk_tier = ? AND p.confidence >= ? AND p.result = 'pending'
          AND m.status = 'scheduled' AND (m.expires_at IS NULL OR m.expires_at > ?)
        ORDER BY p.confidence DESC
    """, (risk_tier, min_confidence, now)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_predictions_for_match(match_id: str, force: bool = False):
    """
    Remove predictions for a match.
    If force=False, skips approved or manual predictions.
    """
    conn = _get_db()
    if force:
        conn.execute("DELETE FROM predictions WHERE match_id = ?", (match_id,))
    else:
        conn.execute("""
            DELETE FROM predictions 
            WHERE match_id = ? AND approved = 0 AND (model_version != 'manual' OR model_version IS NULL)
        """, (match_id,))
    conn.commit()
    conn.close()


# =============================================================================
# RESEARCH CRUD
# =============================================================================

def store_research(match_id: str, research: dict):
    """Store or update research data for a match."""
    conn = _get_db()
    conn.execute("""
        INSERT INTO match_research (match_id, home_form, away_form, home_goals_avg, away_goals_avg,
            home_conceded_avg, away_conceded_avg, home_position, away_position,
            h2h_home_wins, h2h_draws, h2h_away_wins, xg_estimate,
            motivation_factor, injury_impact, research_source, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(match_id) DO UPDATE SET
            home_form=excluded.home_form, away_form=excluded.away_form,
            home_goals_avg=excluded.home_goals_avg, away_goals_avg=excluded.away_goals_avg,
            home_position=excluded.home_position, away_position=excluded.away_position,
            research_source=excluded.research_source, raw_data=excluded.raw_data
    """, (
        match_id,
        research.get("home_form", ""), research.get("away_form", ""),
        research.get("home_goals_avg", 0), research.get("away_goals_avg", 0),
        research.get("home_conceded_avg", 0), research.get("away_conceded_avg", 0),
        research.get("home_position", 0), research.get("away_position", 0),
        research.get("h2h_home_wins", 0), research.get("h2h_draws", 0), research.get("h2h_away_wins", 0),
        research.get("xg_estimate", 0),
        research.get("motivation_factor", ""), research.get("injury_impact", ""),
        research.get("research_source", ""),
        json.dumps(research.get("raw_data", {}))
    ))
    conn.commit()
    conn.close()


def get_research(match_id: str) -> Optional[dict]:
    """Get research data for a match."""
    conn = _get_db()
    row = conn.execute("SELECT * FROM match_research WHERE match_id = ?", (match_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# =============================================================================
# USER SLIP LOGGING
# =============================================================================

def log_user_slip(user_id: int, username: str, slip_text: str,
                  parsed_matches: list, returned_slips: dict):
    """Log a user slip submission."""
    conn = _get_db()
    conn.execute("""
        INSERT INTO user_slips (user_id, username, slip_text, parsed_matches, returned_slips)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, slip_text,
          json.dumps(parsed_matches), json.dumps(returned_slips, default=str)))
    conn.commit()
    conn.close()


# =============================================================================
# GRADING
# =============================================================================

def grade_prediction(prediction_id: int, was_correct: bool,
                     home_goals: int = 0, away_goals: int = 0):
    """Grade a single prediction."""
    conn = _get_db()
    result = "win" if was_correct else "loss"
    conn.execute("""
        UPDATE predictions SET result = ?, graded_at = datetime('now') WHERE id = ?
    """, (result, prediction_id))

    pred = conn.execute("SELECT match_id FROM predictions WHERE id = ?", (prediction_id,)).fetchone()
    actual_result = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"
    conn.execute("""
        INSERT INTO grading_log (match_id, prediction_id, actual_home_goals, actual_away_goals, actual_result, was_correct)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (pred["match_id"], prediction_id, home_goals, away_goals, actual_result, int(was_correct)))
    conn.commit()
    conn.close()


# =============================================================================
# ACCURACY STATS
# =============================================================================

def update_accuracy_stats():
    """Recalculate accuracy stats from grading log."""
    conn = _get_db()

    # Clear existing stats
    conn.execute("DELETE FROM accuracy_stats")

    # Overall by market
    rows = conn.execute("""
        SELECT market, COUNT(*) as total, SUM(was_correct) as wins, AVG(confidence) as avg_conf
        FROM predictions WHERE result IN ('win', 'loss')
        GROUP BY market
    """).fetchall()
    for r in rows:
        acc = round((r["wins"] / r["total"]) * 100, 1) if r["total"] > 0 else 0
        conn.execute("""
            INSERT INTO accuracy_stats (period, market, total, wins, accuracy, avg_confidence)
            VALUES ('all_time', ?, ?, ?, ?, ?)
        """, (r["market"], r["total"], r["wins"], acc, round(r["avg_conf"] or 0, 1)))

    # By risk tier
    rows = conn.execute("""
        SELECT risk_tier, COUNT(*) as total, SUM(was_correct) as wins, AVG(confidence) as avg_conf
        FROM predictions WHERE result IN ('win', 'loss')
        GROUP BY risk_tier
    """).fetchall()
    for r in rows:
        acc = round((r["wins"] / r["total"]) * 100, 1) if r["total"] > 0 else 0
        conn.execute("""
            INSERT INTO accuracy_stats (period, risk_tier, total, wins, accuracy, avg_confidence)
            VALUES ('all_time_tier', ?, ?, ?, ?, ?)
        """, (r["risk_tier"], r["total"], r["wins"], acc, round(r["avg_conf"] or 0, 1)))

    conn.commit()
    conn.close()
    logger.info("Accuracy stats updated")


def get_accuracy_stats() -> list[dict]:
    """Get all accuracy stats."""
    conn = _get_db()
    rows = conn.execute("SELECT * FROM accuracy_stats ORDER BY accuracy DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_pool_summary() -> dict:
    """Get a summary of the prediction pool."""
    conn = _get_db()
    now = datetime.now().isoformat()

    total_matches = conn.execute(
        "SELECT COUNT(*) as c FROM matches WHERE status = 'scheduled' AND (expires_at IS NULL OR expires_at > ?)",
        (now,)
    ).fetchone()["c"]

    total_predictions = conn.execute(
        "SELECT COUNT(*) as c FROM predictions p JOIN matches m ON p.match_id = m.match_id WHERE p.result = 'pending' AND m.status = 'scheduled'",
    ).fetchone()["c"]

    today_matches = conn.execute(
        "SELECT COUNT(*) as c FROM matches WHERE match_date >= ? AND match_date < ? AND status = 'scheduled'",
        (datetime.now().strftime("%Y-%m-%d"), (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d"))
    ).fetchone()["c"]

    avg_conf = conn.execute(
        "SELECT AVG(confidence) as avg_c FROM predictions p JOIN matches m ON p.match_id = m.match_id WHERE p.result = 'pending' AND m.status = 'scheduled'"
    ).fetchone()["avg_c"] or 0

    graded = conn.execute("SELECT COUNT(*) as c FROM predictions WHERE result IN ('win', 'loss')").fetchone()["c"]
    wins = conn.execute("SELECT COUNT(*) as c FROM predictions WHERE result = 'win'").fetchone()["c"]

    conn.close()

    return {
        "active_matches": total_matches,
        "total_predictions": total_predictions,
        "today_matches": today_matches,
        "avg_confidence": round(avg_conf, 1),
        "total_graded": graded,
        "total_wins": wins,
        "overall_accuracy": round((wins / graded) * 100, 1) if graded > 0 else 0,
    }
