"""
Weekly Runner
=============
Runs every Monday at 00:00.
Scrapes next 7 days of football fixtures, scores them, populates prediction pool.
"""

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def run_weekly_cycle():
    """Execute the full weekly prediction cycle."""
    logger.info("=== Weekly Runner: Starting ===")
    t0 = time.time()

    from core.pool_manager import (
        init_pool_db, purge_expired, upsert_match, store_prediction,
        store_research, get_active_matches, clear_predictions_for_match,
    )
    from core.normalizer import normalize_all, count_total_markets
    from core.scoring_engine import calculate_all_scores
    from core.ai_agent import research_and_score_events
    from core.ranker import rank_matches, get_global_pick_pool, filter_diversified_picks

    # Initialize DB
    init_pool_db()

    # Step 1: Purge expired matches
    purged = purge_expired()
    logger.info(f"  Purged {purged} expired matches")

    # Step 2: Scrape next 7 days of fixtures
    logger.info("  Scraping next 7 days of fixtures...")
    all_events = _scrape_week_ahead()

    if not all_events:
        logger.warning("  No events scraped, aborting weekly cycle")
        return {"events": 0, "predictions": 0, "duration": time.time() - t0}

    logger.info(f"  Scraped {len(all_events)} events")

    # Step 3: Normalize
    normalized = normalize_all(all_events)
    stats = count_total_markets(normalized)
    logger.info(f"  Normalized: {stats['total_events']} events")

    # Step 4: Score
    scored = calculate_all_scores(normalized)
    logger.info(f"  Scored {len(scored)} events")

    # Step 5: AI Research (SofaScore today page)
    researched = research_and_score_events(scored)
    logger.info(f"  AI reviewed: {len(researched)} events")

    # Step 6: Rank
    ranked = rank_matches(researched, min_score=50.0, max_matches=50)
    logger.info(f"  Ranked: {len(ranked)} qualifying matches")

    # Step 7: Store in pool
    stored_matches = 0
    stored_preds = 0
    for event in ranked:
        home = event.get("home", "")
        away = event.get("away", "")
        league = event.get("league", "")
        start_ms = event.get("start_time_ms", 0)

        # Build match_id
        match_id = f"sb:{event.get('event_id', '')}"

        # Convert timestamp to ISO date
        match_date = ""
        if start_ms:
            try:
                match_date = datetime.fromtimestamp(start_ms / 1000).isoformat()
            except Exception:
                pass

        if not match_date:
            continue

        # Store match
        upsert_match(match_id, league, match_date, home, away, source="sportybet")
        clear_predictions_for_match(match_id)
        stored_matches += 1

        # Store research if available
        ea = event.get("expert_analysis", {})
        if ea:
            store_research(match_id, {
                "home_form": ea.get("home_form", ""),
                "away_form": ea.get("away_form", ""),
                "home_goals_avg": ea.get("home_goals_scored", 0),
                "away_goals_avg": ea.get("away_goals_scored", 0),
                "home_position": ea.get("home_position", 0),
                "away_position": ea.get("away_position", 0),
                "xg_estimate": ea.get("expected_goals", 0),
                "research_source": event.get("research_source", ""),
            })

        # Store predictions (top 3 picks per match)
        for pick in event.get("scored_picks", []):
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
                },
            )
            stored_preds += 1

    duration = round(time.time() - t0, 1)
    logger.info(f"=== Weekly Runner: Done. {stored_matches} matches, {stored_preds} predictions in {duration}s ===")

    return {
        "events": len(all_events),
        "qualified": len(ranked),
        "matches_stored": stored_matches,
        "predictions_stored": stored_preds,
        "duration": duration,
    }


def _scrape_week_ahead() -> list[dict]:
    """Scrape all upcoming events for the next 7 days."""
    import sys
    import os
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from sportybet_scraper import fetch_upcoming_events

    all_events = []

    # Fetch page 1
    events = fetch_upcoming_events(page_size=100, page_num=1, today_only=False)
    if events:
        all_events.extend(events)

    time.sleep(0.5)

    # Fetch page 2
    events2 = fetch_upcoming_events(page_size=100, page_num=2, today_only=False)
    if events2:
        all_events.extend(events2)

    # Set market_count
    for ev in all_events:
        ev["market_count"] = len(ev.get("markets", {}))

    # Filter to next 7 days only
    now = datetime.now()
    week_ahead = now + timedelta(days=7)
    now_ms = int(now.timestamp() * 1000)
    week_ms = int(week_ahead.timestamp() * 1000)

    filtered = []
    for ev in all_events:
        ts = ev.get("start_time_ms", 0)
        if now_ms <= ts <= week_ms:
            filtered.append(ev)

    return filtered


def _classify_risk(confidence: float) -> str:
    """Classify risk tier from confidence score."""
    if confidence >= 85:
        return "safe"
    elif confidence >= 70:
        return "medium"
    else:
        return "risky"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    result = run_weekly_cycle()
    print(result)
