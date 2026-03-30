"""
AI Consistency Scoring Engine
==============================
Calculates consistency scores (0-100) for each market of each match.

PICK FILTERING RULES:
  - Odds must be between 1.20 and 1.80
  - Minimum tier: A+

Scoring:
  Base Score = implied probability from odds

  Penalties:
    - Draw market: -30%
    - Friendly/low reliability: -25%
    - Aggressive handicap: -15%

  Final Score = adjusted probability score
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

# Hard filters
MIN_ODDS = 1.20
MAX_ODDS = 1.80
MIN_TIER = "A+"


def calculate_all_scores(events: list[dict]) -> list[dict]:
    """Score every market for every event. Returns events with scored picks added."""
    scored_events = []

    for event in events:
        scored = score_event(event)
        if scored:
            scored_events.append(scored)

    logger.info(f"Scored {len(scored_events)} events (odds {MIN_ODDS}-{MAX_ODDS}, tier {MIN_TIER}+)")
    return scored_events


def score_event(event: dict) -> Optional[dict]:
    """Score all markets for a single event.

    Returns the event dict with 'scored_picks' list added, or None if no valid picks.
    """
    markets = event.get("markets", {})
    reliability = event.get("reliability", "low")
    league = event.get("league", "Unknown")

    scored_picks = []

    for market_key, outcomes in markets.items():
        picks = score_market(market_key, outcomes, reliability, league)
        scored_picks.extend(picks)

    if not scored_picks:
        return None

    # Sort by score descending
    scored_picks.sort(key=lambda p: p["consistency_score"], reverse=True)

    # Select top 3 safest picks per match
    top_picks = _select_safest_picks(scored_picks, max_picks=3)

    event["scored_picks"] = top_picks
    event["all_scored_picks"] = scored_picks
    event["best_score"] = top_picks[0]["consistency_score"] if top_picks else 0

    return event


def score_market(market_key: str, outcomes: dict, reliability: str, league: str) -> list[dict]:
    """Score all outcomes in a single market.

    Returns list of pick dicts with consistency scores.
    Only includes picks with odds 1.20-1.80 and tier A+ or better.
    """
    picks = []

    # Calculate implied probabilities
    raw_probs = {}
    for name, odds in outcomes.items():
        if odds > 1.0:
            raw_probs[name] = 100.0 / odds

    total_raw = sum(raw_probs.values())
    if total_raw == 0:
        return []

    # Normalize to remove bookmaker margin
    normalized_probs = {name: (prob / total_raw) * 100 for name, prob in raw_probs.items()}

    for name, odds in outcomes.items():
        # HARD FILTER: odds must be 1.20 - 1.80
        if odds < MIN_ODDS or odds > MAX_ODDS:
            continue

        base_score = normalized_probs.get(name, 0)

        # Apply penalties
        penalty_total = 0
        penalties_applied = []

        # Draw penalty: -30%
        if _is_draw_pick(name, market_key):
            penalty_total += 30
            penalties_applied.append("draw(-30)")

        # Reliability penalty: -25% for low/unreliable
        if reliability in ("low", "unreliable"):
            penalty_total += 25
            penalties_applied.append("reliability(-25)")

        # Aggressive handicap penalty: -15%
        if _is_aggressive_handicap(market_key, name):
            penalty_total += 15
            penalties_applied.append("handicap(-15)")

        # Calculate final score
        final_score = base_score * (1 - penalty_total / 100)
        final_score = max(0, min(100, round(final_score, 1)))

        # Determine tier
        tier = _assign_tier(final_score)

        # HARD FILTER: tier must be A+ or better
        if not _tier_qualifies(tier):
            continue

        # Generate reasoning
        reasoning = _generate_reasoning(name, market_key, odds, base_score, final_score, penalties_applied, reliability)

        picks.append({
            "market": market_key,
            "pick": name,
            "odds": round(odds, 2),
            "implied_prob": round(base_score, 1),
            "consistency_score": final_score,
            "tier": tier,
            "penalties": penalties_applied,
            "reasoning": reasoning,
        })

    return picks


def _tier_qualifies(tier: str) -> bool:
    """Check if tier meets minimum threshold (A+ or better)."""
    tier_rank = {
        "S+": 6, "S": 5, "A+": 4, "A": 3, "B+": 2, "B": 1, "C": 0, "D": -1,
    }
    min_rank = tier_rank.get(MIN_TIER, 4)
    pick_rank = tier_rank.get(tier, -1)
    return pick_rank >= min_rank


def _is_draw_pick(name: str, market_key: str) -> bool:
    """Check if this is a draw pick."""
    name_lower = name.lower().strip()
    if name_lower in ("draw", "x", "tie", "d"):
        return True
    if "draw" in name_lower and "1x2" in market_key.lower():
        return True
    return False


def _is_aggressive_handicap(market_key: str, outcome_name: str) -> bool:
    """Check if this is an aggressive handicap (-2 or more)."""
    if "handicap" not in market_key.lower():
        return False

    match = re.search(r'(-?\d+)', outcome_name)
    if match:
        val = abs(int(match.group(1)))
        if val >= 2:
            return True

    match = re.search(r'hcp=(\d+)', market_key)
    if match:
        val = int(match.group(1))
        if val >= 2:
            return True

    return False


def _assign_tier(score: float) -> str:
    """Assign a tier label based on consistency score."""
    if score >= 85:
        return "S+"
    elif score >= 75:
        return "S"
    elif score >= 68:
        return "A+"
    elif score >= 60:
        return "A"
    elif score >= 52:
        return "B+"
    elif score >= 45:
        return "B"
    elif score >= 35:
        return "C"
    else:
        return "D"


def _generate_reasoning(
    pick_name: str,
    market: str,
    odds: float,
    base_score: float,
    final_score: float,
    penalties: list[str],
    reliability: str,
) -> str:
    """Generate a short human-readable reasoning for the pick."""
    parts = []

    if base_score >= 70:
        parts.append(f"Strong implied probability ({base_score:.1f}%)")
    elif base_score >= 55:
        parts.append(f"Solid implied probability ({base_score:.1f}%)")
    else:
        parts.append(f"Implied probability ({base_score:.1f}%)")

    if not penalties:
        parts.append("No penalty flags")

    if reliability == "high":
        parts.append("Tier-1 league")

    if final_score >= 75:
        parts.append("Elite consistency")
    elif final_score >= 65:
        parts.append("High consistency")
    else:
        parts.append("Good consistency")

    return " | ".join(parts)


def _select_safest_picks(picks: list[dict], max_picks: int = 3) -> list[dict]:
    """Select the top N safest picks (highest consistency score, diverse markets)."""
    if len(picks) <= max_picks:
        return picks

    selected = []
    used_markets = set()

    # First pass: pick best from distinct markets
    for pick in picks:
        if len(selected) >= max_picks:
            break
        market = pick.get("market", "")
        if market not in used_markets:
            selected.append(pick)
            used_markets.add(market)

    # Fill remaining slots if needed
    for pick in picks:
        if len(selected) >= max_picks:
            break
        if pick not in selected:
            selected.append(pick)

    return selected[:max_picks]


def implied_probability(odds: float) -> float:
    """Convert decimal odds to implied probability (0-100)."""
    if odds <= 1.0:
        return 0.0
    return round(100.0 / odds, 1)


def true_probability(odds_list: list[float]) -> list[float]:
    """Calculate true probabilities by removing bookmaker margin."""
    raw = [1.0 / o if o > 1.0 else 0 for o in odds_list]
    total = sum(raw)
    if total == 0:
        return [0] * len(odds_list)
    return [round(r / total * 100, 1) for r in raw]
