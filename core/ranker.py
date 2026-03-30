"""
Match Ranking System
====================
Ranks matches globally by their best market score.
Filters out matches where best score < 60.
Keeps top 15-25 matches for the day.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def rank_matches(scored_events: list[dict], min_score: float = 60.0, max_matches: int = 25) -> list[dict]:
    """Rank matches globally by their best market score.

    Args:
        scored_events: Events with scored_picks attached by scoring_engine
        min_score: Minimum consistency score to include (default 60)
        max_matches: Maximum number of matches to keep (default 25)

    Returns:
        Ranked list of events, sorted by best_score descending.
    """
    # Filter by minimum score
    qualified = [ev for ev in scored_events if ev.get("best_score", 0) >= min_score]

    logger.info(f"Score filter: {len(qualified)}/{len(scored_events)} events above {min_score} threshold")

    # Sort by best score descending
    qualified.sort(key=lambda e: e.get("best_score", 0), reverse=True)

    # Cap at max_matches
    ranked = qualified[:max_matches]

    # Assign ranks
    for i, event in enumerate(ranked, 1):
        event["rank"] = i

    logger.info(f"Final ranking: {len(ranked)} matches selected")
    return ranked


def get_global_pick_pool(ranked_events: list[dict]) -> list[dict]:
    """Extract all picks from ranked events into a single flat list.

    Each pick is enriched with match context and globally ranked.
    """
    all_picks = []

    for event in ranked_events:
        for pick in event.get("scored_picks", []):
            enriched = {
                **pick,
                "home": event.get("home", ""),
                "away": event.get("away", ""),
                "match": f"{event.get('home', '')} vs {event.get('away', '')}",
                "league": event.get("league", ""),
                "start_time_ms": event.get("start_time_ms", 0),
                "event_id": event.get("event_id", ""),
                "reliability": event.get("reliability", "medium"),
                "match_rank": event.get("rank", 999),
            }
            all_picks.append(enriched)

    # Sort by consistency score descending
    all_picks.sort(key=lambda p: p["consistency_score"], reverse=True)

    # Assign global rank
    for i, pick in enumerate(all_picks, 1):
        pick["global_rank"] = i

    return all_picks


def filter_diversified_picks(picks: list[dict], max_per_match: int = 2, max_per_market: int = 4) -> list[dict]:
    """Filter picks ensuring diversity across matches and markets.

    Args:
        picks: Globally ranked picks
        max_per_match: Max picks from the same match
        max_per_market: Max picks from the same market type
    """
    match_count = {}
    market_count = {}
    selected = []

    for pick in picks:
        eid = pick.get("event_id", "")
        mkt = pick.get("market", "")

        if match_count.get(eid, 0) >= max_per_match:
            continue
        if market_count.get(mkt, 0) >= max_per_market:
            continue

        selected.append(pick)
        match_count[eid] = match_count.get(eid, 0) + 1
        market_count[mkt] = market_count.get(mkt, 0) + 1

    return selected


def get_ranking_summary(ranked_events: list[dict]) -> dict:
    """Generate a summary of the ranking results."""
    if not ranked_events:
        return {
            "total_matches": 0,
            "score_range": "N/A",
            "leagues": [],
            "reliability_breakdown": {},
        }

    scores = [e.get("best_score", 0) for e in ranked_events]
    leagues = list(set(e.get("league", "") for e in ranked_events))

    return {
        "total_matches": len(ranked_events),
        "score_range": f"{min(scores):.1f} - {max(scores):.1f}",
        "avg_score": round(sum(scores) / len(scores), 1),
        "leagues": sorted(leagues),
        "reliability_breakdown": {
            level: sum(1 for e in ranked_events if e.get("reliability") == level)
            for level in ["high", "medium", "low"]
        },
        "top_3": [
            {
                "match": f"{e['home']} vs {e['away']}",
                "score": e.get("best_score", 0),
                "league": e.get("league", ""),
            }
            for e in ranked_events[:3]
        ],
    }
