"""
Daily Refresh
=============
Runs at 06:00 and 18:00.
Re-scrapes odds for today and tomorrow matches.
Detects significant odds movement (>15%) and re-scores affected predictions.
"""

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def run_daily_refresh():
    """Refresh odds and form for today/tomorrow matches."""
    logger.info("=== Daily Refresh: Starting ===")
    t0 = time.time()

    from core.pool_manager import (
        init_pool_db, get_today_matches, get_tomorrow_matches,
        clear_predictions_for_match, store_prediction, store_research,
    )
    from core.normalizer import normalize_all
    from core.scoring_engine import calculate_all_scores
    from core.ai_agent import research_and_score_events

    init_pool_db()

    # Get matches to refresh
    today = get_today_matches()
    tomorrow = get_tomorrow_matches()
    matches_to_refresh = today + tomorrow

    if not matches_to_refresh:
        logger.info("  No matches to refresh")
        return {"refreshed": 0, "movement_detected": 0}

    logger.info(f"  Refreshing {len(matches_to_refresh)} matches ({len(today)} today, {len(tomorrow)} tomorrow)")

    # Re-scrape current odds
    fresh_events = _scrape_current_odds()

    if not fresh_events:
        logger.warning("  Could not scrape fresh odds")
        return {"refreshed": 0, "movement_detected": 0}

    # Normalize and score fresh data
    normalized = normalize_all(fresh_events)
    scored = calculate_all_scores(normalized)
    researched = research_and_score_events(scored)

    # Match against pool and detect movement
    movement_count = 0
    refreshed_count = 0

    for pool_match in matches_to_refresh:
        pool_home = pool_match["home_team"].lower()
        pool_away = pool_match["away_team"].lower()

        # Find matching fresh event
        fresh_match = None
        for ev in researched:
            ev_home = ev.get("home", "").lower()
            ev_away = ev.get("away", "").lower()
            if pool_home in ev_home or ev_home in pool_home:
                if pool_away in ev_away or ev_away in pool_away:
                    fresh_match = ev
                    break

        if not fresh_match:
            continue

        # Check for significant odds movement
        has_movement = _detect_odds_movement(pool_match, fresh_match)

        if has_movement:
            movement_count += 1
            logger.info(f"  Odds movement detected: {pool_match['home_team']} vs {pool_match['away_team']}")

        # Always refresh today's matches, only refresh tomorrow if movement detected
        match_dt = pool_match.get("match_date", "")
        is_today = match_dt.startswith(datetime.now().strftime("%Y-%m-%d"))

        if is_today or has_movement:
            match_id = pool_match["match_id"]
            clear_predictions_for_match(match_id)

            for pick in fresh_match.get("scored_picks", []):
                risk_tier = _classify_risk(pick.get("expert_confidence", 0))
                store_prediction(
                    match_id=match_id,
                    market=pick.get("market", ""),
                    pick=pick.get("pick", ""),
                    odds=pick.get("odds", 0),
                    confidence=pick.get("expert_confidence", 0),
                    risk_tier=risk_tier,
                    reasoning=pick.get("expert_reasoning", pick.get("reasoning", "")),
                    source_data={
                        "consistency_score": pick.get("consistency_score", 0),
                        "tier": pick.get("tier", ""),
                        "refreshed": True,
                        "odds_movement": has_movement,
                    },
                )

            # Update research
            ea = fresh_match.get("expert_analysis", {})
            if ea:
                store_research(match_id, {
                    "home_form": ea.get("home_form", ""),
                    "away_form": ea.get("away_form", ""),
                    "home_goals_avg": ea.get("home_goals_scored", 0),
                    "away_goals_avg": ea.get("away_goals_scored", 0),
                    "xg_estimate": ea.get("expected_goals", 0),
                    "research_source": fresh_match.get("research_source", ""),
                })

            refreshed_count += 1

    duration = round(time.time() - t0, 1)
    logger.info(f"=== Daily Refresh: Done. {refreshed_count} refreshed, {movement_count} with movement in {duration}s ===")

    return {
        "total_matches": len(matches_to_refresh),
        "refreshed": refreshed_count,
        "movement_detected": movement_count,
        "duration": duration,
    }


def _scrape_current_odds() -> list[dict]:
    """Scrape current odds from SportyBet."""
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from sportybet_scraper import fetch_upcoming_events

    events = fetch_upcoming_events(page_size=100, page_num=1, today_only=False)
    if not events:
        events = fetch_upcoming_events(page_size=100, page_num=1, today_only=True)

    for ev in events:
        ev["market_count"] = len(ev.get("markets", {}))

    return events


def _detect_odds_movement(pool_match: dict, fresh_event: dict) -> bool:
    """Detect if odds have moved significantly (>15%) for any market."""
    from core.pool_manager import get_predictions_for_match

    old_preds = get_predictions_for_match(pool_match["match_id"])
    if not old_preds:
        return False

    fresh_markets = fresh_event.get("markets", {})

    for old_pred in old_preds:
        market = old_pred["market"]
        pick = old_pred["pick"]
        old_odds = old_pred["odds"]

        # Find matching fresh odds
        if market in fresh_markets:
            outcomes = fresh_markets[market]
            new_odds = outcomes.get(pick, 0)
            if new_odds > 0 and old_odds > 0:
                change = abs(new_odds - old_odds) / old_odds
                if change > 0.15:
                    return True

    return False


def _classify_risk(confidence: float) -> str:
    if confidence >= 85:
        return "safe"
    elif confidence >= 70:
        return "medium"
    return "risky"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    result = run_daily_refresh()
    print(result)
