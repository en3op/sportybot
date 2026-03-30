"""
Historical Tracking Module
==========================
Stores daily results and tracks win/loss per market type.
Adjusts scoring weights over time (self-learning).
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "history.db")


def _get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_history_db():
    """Create history tables if they don't exist."""
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS daily_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_date TEXT NOT NULL,
            run_time TEXT NOT NULL,
            total_events INTEGER DEFAULT 0,
            qualified_events INTEGER DEFAULT 0,
            total_picks INTEGER DEFAULT 0,
            safe_slip_odds REAL DEFAULT 0,
            moderate_slip_odds REAL DEFAULT 0,
            high_slip_odds REAL DEFAULT 0,
            output_json TEXT,
            status TEXT DEFAULT 'generated'
        );

        CREATE TABLE IF NOT EXISTS individual_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER,
            run_date TEXT NOT NULL,
            event_id TEXT,
            home TEXT,
            away TEXT,
            league TEXT,
            market TEXT,
            pick TEXT,
            odds REAL,
            consistency_score REAL,
            tier TEXT,
            slip_type TEXT,
            result TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (run_id) REFERENCES daily_runs(id)
        );

        CREATE TABLE IF NOT EXISTS market_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market TEXT NOT NULL,
            total_picks INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            pending INTEGER DEFAULT 0,
            avg_score REAL DEFAULT 0,
            win_rate REAL DEFAULT 0,
            last_updated TEXT DEFAULT (datetime('now')),
            UNIQUE(market)
        );

        CREATE TABLE IF NOT EXISTS weight_adjustments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            adjustment_date TEXT NOT NULL,
            penalty_name TEXT,
            old_value REAL,
            new_value REAL,
            reason TEXT
        );
    """)
    conn.commit()
    conn.close()
    logger.info("History database initialized")


def store_daily_run(output: dict) -> int:
    """Store a daily run result. Returns the run_id."""
    conn = _get_db()
    date_str = output.get("date", datetime.now().strftime("%Y-%m-%d"))
    time_str = datetime.now().strftime("%H:%M:%S")

    safe_odds = output.get("metadata", {}).get("safe_combined_odds", 0)
    mod_odds = output.get("metadata", {}).get("moderate_combined_odds", 0)
    high_odds = output.get("metadata", {}).get("high_combined_odds", 0)

    output_json = json.dumps(output, default=str)

    cursor = conn.execute("""
        INSERT INTO daily_runs (run_date, run_time, total_events, qualified_events,
                                total_picks, safe_slip_odds, moderate_slip_odds, high_slip_odds,
                                output_json, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'generated')
    """, (
        date_str, time_str,
        output.get("total_events", 0),
        output.get("qualified_events", 0),
        output.get("total_picks", 0),
        safe_odds, mod_odds, high_odds,
        output_json,
    ))
    run_id = cursor.lastrowid or 0

    # Store individual picks
    for slip_type in ["safe_slip", "moderate_slip", "high_slip"]:
        for pick in output.get(slip_type, []):
            conn.execute("""
                INSERT INTO individual_picks (run_id, run_date, event_id, home, away, league,
                                              market, pick, odds, consistency_score, tier, slip_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, date_str,
                pick.get("event_id", ""),
                pick.get("home", ""),
                pick.get("away", ""),
                pick.get("league", ""),
                pick.get("market", ""),
                pick.get("pick", ""),
                pick.get("odds", 0),
                pick.get("consistency_score", 0),
                pick.get("tier", ""),
                slip_type,
            ))

    conn.commit()
    conn.close()

    logger.info(f"Stored daily run #{run_id} for {date_str}")
    return run_id


def update_pick_result(pick_id: int, result: str):
    """Update a pick's result: 'win', 'loss', or 'void'."""
    conn = _get_db()
    conn.execute("UPDATE individual_picks SET result = ? WHERE id = ?", (result, pick_id))

    # Also update market stats
    pick = conn.execute("SELECT market FROM individual_picks WHERE id = ?", (pick_id,)).fetchone()
    if pick:
        market = pick["market"]
        existing = conn.execute("SELECT * FROM market_stats WHERE market = ?", (market,)).fetchone()

        if existing:
            wins = existing["wins"] + (1 if result == "win" else 0)
            losses = existing["losses"] + (1 if result == "loss" else 0)
            total = wins + losses
            win_rate = round(wins / total * 100, 1) if total > 0 else 0
            conn.execute("""
                UPDATE market_stats SET wins = ?, losses = ?, win_rate = ?, last_updated = datetime('now')
                WHERE market = ?
            """, (wins, losses, win_rate, market))
        else:
            wins = 1 if result == "win" else 0
            losses = 1 if result == "loss" else 0
            conn.execute("""
                INSERT INTO market_stats (market, total_picks, wins, losses, win_rate)
                VALUES (?, 1, ?, ?, ?)
            """, (market, wins, losses, round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0))

    conn.commit()
    conn.close()


def get_market_performance() -> list[dict]:
    """Get win/loss stats per market type."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT market, total_picks, wins, losses, pending, win_rate
        FROM market_stats ORDER BY win_rate DESC
    """).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_recent_runs(days: int = 30) -> list[dict]:
    """Get daily run history for the last N days."""
    conn = _get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT id, run_date, run_time, total_events, qualified_events,
               total_picks, safe_slip_odds, moderate_slip_odds, high_slip_odds, status
        FROM daily_runs WHERE run_date >= ? ORDER BY run_date DESC
    """, (cutoff,)).fetchall()
    conn.close()

    return [dict(r) for r in rows]


def get_scoring_weights() -> dict:
    """Get current scoring weights (for self-learning adjustments)."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT penalty_name, new_value FROM weight_adjustments
        ORDER BY adjustment_date DESC
    """).fetchall()
    conn.close()

    # Default weights
    weights = {
        "draw_penalty": 30,
        "high_odds_penalty": 20,
        "reliability_penalty": 25,
        "handicap_penalty": 15,
    }

    # Override with any adjustments
    for row in rows:
        name = row["penalty_name"]
        if name in weights:
            weights[name] = row["new_value"]

    return weights


def adjust_weights_based_on_history():
    """Self-learning: adjust scoring weights based on historical performance."""
    conn = _get_db()

    # Get market performance
    market_perf = conn.execute("""
        SELECT market, win_rate, total_picks FROM market_stats
        WHERE total_picks >= 5
    """).fetchall()

    if not market_perf:
        conn.close()
        return

    # Analyze which markets are performing best
    good_markets = [r for r in market_perf if r["win_rate"] >= 55]
    bad_markets = [r for r in market_perf if r["win_rate"] < 40]

    date_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if bad_markets:
        # Increase penalty for consistently bad markets
        for bm in bad_markets:
            market_name = bm["market"]
            if "draw" in market_name.lower():
                conn.execute("""
                    INSERT INTO weight_adjustments (adjustment_date, penalty_name, old_value, new_value, reason)
                    VALUES (?, 'draw_penalty', 30, 35, 'Draw market win rate below 40%')
                """, (date_str,))

    if good_markets:
        logger.info(f"Markets performing well: {[m['market'] for m in good_markets]}")

    conn.commit()
    conn.close()
    logger.info("Weight adjustment check completed")


def get_run_output(run_id: int) -> Optional[dict]:
    """Retrieve the full output JSON for a specific run."""
    conn = _get_db()
    row = conn.execute("SELECT output_json FROM daily_runs WHERE id = ?", (run_id,)).fetchone()
    conn.close()

    if row and row["output_json"]:
        return json.loads(row["output_json"])
    return None
