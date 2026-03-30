"""
Slip Generation Engine
======================
Generates 3 slip types from ranked picks:
  - SAFE: Top 3-5 highest scoring picks, odds target 2.0-3.0
  - MODERATE: Top 5-6 picks, odds target 2.5-3.5
  - HIGH: Top 5-7 picks, odds target 3.0-4.5

ALL picks must have odds between 1.20 and 1.80.
"""

import logging
import functools
from typing import Optional

logger = logging.getLogger(__name__)

# Hard odds filter (must match scoring_engine)
MIN_ODDS = 1.20
MAX_ODDS = 1.80


def generate_all_slips(global_picks: list[dict]) -> dict:
    """Generate all 3 slip types from the global pick pool.

    Returns dict with safe_slip, moderate_slip, high_slip, and metadata.
    All picks must have odds 1.20-1.80.
    """
    # Pre-filter: only keep picks within odds range
    filtered = [p for p in global_picks if MIN_ODDS <= p.get("odds", 0) <= MAX_ODDS]
    logger.info(f"Odds filter {MIN_ODDS}-{MAX_ODDS}: {len(filtered)}/{len(global_picks)} picks qualify")

    if not filtered:
        return _empty_result()

    safe = _generate_safe_slip(filtered)
    moderate = _generate_moderate_slip(filtered)
    high = _generate_high_slip(filtered)

    return {
        "safe_slip": safe,
        "moderate_slip": moderate,
        "high_slip": high,
        "metadata": {
            "total_picks_available": len(filtered),
            "safe_combined_odds": _combined_odds(safe),
            "moderate_combined_odds": _combined_odds(moderate),
            "high_combined_odds": _combined_odds(high),
        },
    }


def _generate_safe_slip(picks: list[dict]) -> list[dict]:
    """SAFE slip: max 3.0 combined odds."""
    return _build_slip(
        picks=picks,
        min_legs=2,
        max_legs=5,
        target_min=1.5,
        target_max=3.0,
        label="SAFE",
    )


def _generate_moderate_slip(picks: list[dict]) -> list[dict]:
    """MODERATE slip: max 7.0 combined odds."""
    return _build_slip(
        picks=picks,
        min_legs=3,
        max_legs=8,
        target_min=2.5,
        target_max=7.0,
        label="MODERATE",
    )


def _generate_high_slip(picks: list[dict]) -> list[dict]:
    """HIGH slip: max 10.0 combined odds."""
    return _build_slip(
        picks=picks,
        min_legs=4,
        max_legs=10,
        target_min=4.0,
        target_max=10.0,
        label="HIGH",
    )


def _build_slip(
    picks: list[dict],
    min_legs: int,
    max_legs: int,
    target_min: float,
    target_max: float,
    label: str,
) -> list[dict]:
    """Build a slip from picks matching constraints.

    Greedily selects highest-scoring picks that:
      - Odds between 1.20 and 1.80 (already filtered)
      - Combined odds stay within target range
      - No duplicate matches
    """
    selected = []
    used_events = set()
    current_odds = 1.0

    for pick in picks:
        if len(selected) >= max_legs:
            break

        eid = pick.get("event_id", "")
        odds = pick.get("odds", 0)

        # Skip if match already used
        if eid in used_events:
            continue

        # Check if adding this pick keeps us in target range
        projected = current_odds * odds
        if projected > target_max * 1.15:
            continue

        selected.append(pick)
        used_events.add(eid)
        current_odds = projected

    # If we didn't reach minimum legs, relax the target cap
    if len(selected) < min_legs:
        for pick in picks:
            if len(selected) >= min_legs:
                break
            eid = pick.get("event_id", "")
            if eid in used_events:
                continue
            selected.append(pick)
            used_events.add(eid)

    # Sort selected by consistency score descending
    selected.sort(key=lambda p: p.get("consistency_score", 0), reverse=True)

    combined = _combined_odds(selected)
    logger.info(f"{label} slip: {len(selected)} picks, combined {combined:.2f}x")
    return selected


def _combined_odds(picks: list[dict]) -> float:
    """Calculate combined accumulator odds."""
    if not picks:
        return 0.0
    return round(functools.reduce(lambda x, y: x * y, [p.get("odds", 1.0) for p in picks], 1.0), 2)


def _empty_result() -> dict:
    """Return empty slip structure."""
    return {
        "safe_slip": [],
        "moderate_slip": [],
        "high_slip": [],
        "metadata": {
            "total_picks_available": 0,
            "safe_combined_odds": 0,
            "moderate_combined_odds": 0,
            "high_combined_odds": 0,
        },
    }


def format_slip_for_display(slip: list[dict], label: str, risk_level: str) -> str:
    """Format a slip for Telegram display."""
    if not slip:
        return f"{label} ({risk_level}): No picks available"

    combined = _combined_odds(slip)
    lines = [f"{label} ({combined:.2f}x) - {risk_level}", "-" * 28]

    for i, pick in enumerate(slip, 1):
        match_str = pick.get("match", f"{pick.get('home', '')} vs {pick.get('away', '')}")
        lines.append(f"  {i}. {match_str}")
        lines.append(f"     {pick.get('market', '')}: {pick.get('pick', '')} @ {pick.get('odds', 0):.2f}")
        lines.append(f"     Score: {pick.get('consistency_score', 0):.1f} | Tier {pick.get('tier', 'B')}")
        if pick.get("reasoning"):
            lines.append(f"     {pick['reasoning']}")
        lines.append("")

    return "\n".join(lines)
