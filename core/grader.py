"""
Prediction Grader
=================
Auto-grades finished matches against predictions.
Updates accuracy stats for continuous improvement.
"""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def grade_finished_matches():
    """Grade all pending predictions for finished matches."""
    logger.info("=== Grader: Starting ===")

    from core.pool_manager import _get_db, update_accuracy_stats

    conn = _get_db()

    # Find predictions that are pending but their match has been marked finished
    pending = conn.execute("""
        SELECT p.id, p.match_id, p.market, p.pick, p.odds, p.confidence,
               m.home_team, m.away_team, m.status
        FROM predictions p
        JOIN matches m ON p.match_id = m.match_id
        WHERE p.result = 'pending' AND m.status = 'finished'
    """).fetchall()

    if not pending:
        logger.info("  No pending predictions to grade")
        conn.close()
        return {"graded": 0, "wins": 0}

    # Try to get final scores from grading_log (if already set by external scorer)
    wins = 0
    losses = 0

    for pred in pending:
        pred_id = pred["id"]
        match_id = pred["match_id"]
        market = pred["market"]
        pick = pred["pick"]

        # Check if we have a final score in grading_log
        log_entry = conn.execute(
            "SELECT actual_home_goals, actual_away_goals FROM grading_log WHERE match_id = ? LIMIT 1",
            (match_id,)
        ).fetchone()

        if log_entry:
            hg = log_entry["actual_home_goals"]
            ag = log_entry["actual_away_goals"]
            correct = _grade_prediction(market, pick, hg, ag)
        else:
            # Can't grade without final score - mark as void
            conn.execute("UPDATE predictions SET result = 'void', graded_at = datetime('now') WHERE id = ?", (pred_id,))
            conn.commit()
            continue

        result = "win" if correct else "loss"
        conn.execute("UPDATE predictions SET result = ?, graded_at = datetime('now') WHERE id = ?", (result, pred_id))

        # Log grading
        actual_result = "home" if hg > ag else "away" if ag > hg else "draw"
        conn.execute("""
            INSERT INTO grading_log (match_id, prediction_id, actual_home_goals, actual_away_goals, actual_result, was_correct)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (match_id, pred_id, hg, ag, actual_result, int(correct)))

        if correct:
            wins += 1
        else:
            losses += 1

    conn.commit()
    conn.close()

    # Update accuracy stats
    update_accuracy_stats()

    logger.info(f"=== Grader: Done. {wins}W / {losses}L ===")
    return {"graded": wins + losses, "wins": wins, "losses": losses}


def set_match_result(match_id: str, home_goals: int, away_goals: int):
    """Set the final score for a match and mark it as finished."""
    from core.pool_manager import _get_db

    conn = _get_db()
    conn.execute("UPDATE matches SET status = 'finished' WHERE match_id = ?", (match_id,))

    # Check if grading_log entry exists
    existing = conn.execute(
        "SELECT id FROM grading_log WHERE match_id = ? LIMIT 1", (match_id,)
    ).fetchone()

    actual_result = "home" if home_goals > away_goals else "away" if away_goals > home_goals else "draw"

    if existing:
        conn.execute("""
            UPDATE grading_log SET actual_home_goals = ?, actual_away_goals = ?, actual_result = ?
            WHERE match_id = ?
        """, (home_goals, away_goals, actual_result, match_id))
    else:
        conn.execute("""
            INSERT INTO grading_log (match_id, actual_home_goals, actual_away_goals, actual_result)
            VALUES (?, ?, ?, ?)
        """, (match_id, home_goals, away_goals, actual_result))

    conn.commit()
    conn.close()
    logger.info(f"Set result for {match_id}: {home_goals}-{away_goals}")


def _grade_prediction(market: str, pick: str, home_goals: int, away_goals: int) -> bool:
    """Grade a single prediction against actual result."""
    total = home_goals + away_goals
    result = "Home" if home_goals > away_goals else "Away" if away_goals > home_goals else "Draw"

    market_lower = market.lower()

    # 1X2
    if "1x2" in market_lower or market_lower in ("match result", "home/away"):
        return pick == result or (pick == "1" and result == "Home") or (pick == "2" and result == "Away") or (pick == "X" and result == "Draw")

    # Over/Under
    if "over" in market_lower or "under" in market_lower:
        import re
        line_match = re.search(r'(\d+\.?\d*)', market)
        if line_match:
            line = float(line_match.group(1))
            if "over" in pick.lower():
                return total > line
            elif "under" in pick.lower():
                return total < line

    # BTTS
    if "btts" in market_lower or "both" in market_lower.lower():
        both_scored = home_goals > 0 and away_goals > 0
        if "yes" in pick.lower():
            return both_scored
        elif "no" in pick.lower():
            return not both_scored

    # Double Chance
    if "double" in market_lower or "chance" in market_lower:
        if "1X" in pick or "1x" in pick:
            return home_goals >= away_goals
        if "X2" in pick or "x2" in pick:
            return away_goals >= home_goals
        if "12" in pick:
            return home_goals != away_goals

    # DNB
    if "dnb" in market_lower or "draw no bet" in market_lower:
        if result == "Draw":
            return True  # void, count as correct
        return pick == result

    # Handicap
    if "handicap" in market_lower:
        import re
        # Try to extract handicap value from market or pick
        hcp_match = re.search(r'(\d+)', pick)
        if hcp_match:
            hcp = int(hcp_match.group(1))
            if "home" in pick.lower() or pick.startswith("1"):
                return (home_goals + hcp) > away_goals
            elif "away" in pick.lower() or pick.startswith("2"):
                return (away_goals + hcp) > home_goals

    # Default: can't grade
    return False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = grade_finished_matches()
    print(result)
