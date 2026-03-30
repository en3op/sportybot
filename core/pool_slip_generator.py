"""
Pool Slip Generator
===================
Builds Safe / Medium / Risky slips from prediction pool data.
"""

import logging
import functools
from datetime import datetime

logger = logging.getLogger(__name__)


def generate_slips_from_matches(matched_data: list[dict]) -> dict:
    """Generate 3 slip types from matched pool predictions.

    Args:
        matched_data: List of {slip_match, pool_match, predictions, research}

    Returns dict with safe_slip, medium_slip, risky_slip and metadata.
    """
    # Collect all predictions from all matched matches
    all_picks = []
    for entry in matched_data:
        pool_match = entry["pool_match"]
        research = entry.get("research", {})
        for pred in entry.get("predictions", []):
            pick = {
                "match": f"{pool_match['home_team']} vs {pool_match['away_team']}",
                "home": pool_match["home_team"],
                "away": pool_match["away_team"],
                "league": pool_match.get("league", ""),
                "match_date": pool_match.get("match_date", ""),
                "market": pred["market"],
                "pick": pred["pick"],
                "odds": pred["odds"],
                "confidence": pred["confidence"],
                "risk_tier": pred["risk_tier"],
                "reasoning": pred.get("reasoning", ""),
                "match_id": pred.get("match_id", ""),
                # Research data
                "home_form": research.get("home_form", ""),
                "away_form": research.get("away_form", ""),
                "home_position": research.get("home_position", 0),
                "away_position": research.get("away_position", 0),
                "home_goals_avg": research.get("home_goals_avg", 0),
                "away_goals_avg": research.get("away_goals_avg", 0),
            }
            all_picks.append(pick)

    if not all_picks:
        return _empty_result()

    # Sort by confidence descending
    all_picks.sort(key=lambda p: p["confidence"], reverse=True)

    safe = _build_slip(all_picks, min_conf=90, max_legs=5, target_min=2.0, target_max=5.0, label="SAFE")
    medium = _build_slip(all_picks, min_conf=70, max_legs=6, target_min=3.0, target_max=8.0, label="MEDIUM")
    risky = _build_slip(all_picks, min_conf=0, max_legs=7, target_min=5.0, target_max=15.0, label="RISKY")

    return {
        "safe_slip": safe,
        "medium_slip": medium,
        "risky_slip": risky,
        "metadata": {
            "total_picks_available": len(all_picks),
            "safe_combined_odds": _combined_odds(safe),
            "safe_count": len(safe),
            "medium_combined_odds": _combined_odds(medium),
            "medium_count": len(medium),
            "risky_combined_odds": _combined_odds(risky),
            "risky_count": len(risky),
        },
    }


def _build_slip(picks: list[dict], min_conf: float, max_legs: int,
                target_min: float, target_max: float, label: str) -> list[dict]:
    """Build a slip from picks matching constraints."""
    # Filter by minimum confidence
    if min_conf > 0:
        filtered = [p for p in picks if p["confidence"] >= min_conf]
    else:
        filtered = picks[:]

    selected = []
    used_matches = set()
    current_odds = 1.0

    for pick in filtered:
        if len(selected) >= max_legs:
            break

        mid = pick["match_id"]
        if mid in used_matches:
            continue

        odds = pick["odds"]
        if odds < 1.10 or odds > 5.0:
            continue

        projected = current_odds * odds
        if projected > target_max * 1.2:
            continue

        selected.append(pick)
        used_matches.add(mid)
        current_odds = projected

    # Fill to minimum if needed
    if len(selected) < 2 and picks:
        for pick in picks:
            if len(selected) >= 2:
                break
            mid = pick["match_id"]
            if mid not in used_matches:
                selected.append(pick)
                used_matches.add(mid)

    combined = _combined_odds(selected)
    stake = _suggest_stake(label, combined)

    for pick in selected:
        pick["ev_estimate"] = _estimate_ev(pick["confidence"], pick["odds"])

    logger.info(f"{label} slip: {len(selected)} picks, {combined:.2f}x, stake: {stake}")
    return selected


def _combined_odds(picks: list[dict]) -> float:
    if not picks:
        return 0.0
    return round(functools.reduce(lambda x, y: x * y, [p["odds"] for p in picks], 1.0), 2)


def _suggest_stake(label: str, combined_odds: float) -> str:
    if label == "SAFE":
        return "3-5% of bankroll"
    elif label == "MEDIUM":
        return "1-3% of bankroll"
    return "0.5-1% of bankroll"


def _estimate_ev(confidence: float, odds: float) -> str:
    """Estimate expected value percentage."""
    true_prob = confidence / 100.0
    ev = (true_prob * odds) - 1.0
    pct = round(ev * 100, 1)
    if pct > 0:
        return f"+{pct}%"
    return f"{pct}%"


def _empty_result() -> dict:
    return {
        "safe_slip": [],
        "medium_slip": [],
        "risky_slip": [],
        "metadata": {
            "total_picks_available": 0,
            "safe_combined_odds": 0, "safe_count": 0,
            "medium_combined_odds": 0, "medium_count": 0,
            "risky_combined_odds": 0, "risky_count": 0,
        },
    }


def format_slip_telegram(slip: list[dict], label: str, risk_level: str) -> str:
    """Format a slip for Telegram display."""
    if not slip:
        return f"{label} ({risk_level}): No qualifying picks found"

    combined = _combined_odds(slip)
    stake = _suggest_stake(label, combined)

    lines = [
        f"{label} SLIP ({combined:.2f}x) - {risk_level}",
        f"Suggested stake: {stake}",
        "-" * 28,
    ]

    for i, pick in enumerate(slip, 1):
        ev = _estimate_ev(pick["confidence"], pick["odds"])
        lines.append(f"  {i}. {pick['match']}")
        lines.append(f"     {pick['league']}")
        lines.append(f"     {pick['market']}: {pick['pick']} @ {pick['odds']:.2f}")
        lines.append(f"     Confidence: {pick['confidence']:.0f}/100 | EV: {ev}")

        # Form data if available
        hf = pick.get("home_form", "")
        af = pick.get("away_form", "")
        if hf or af:
            hp = pick.get("home_position", 0)
            ap = pick.get("away_position", 0)
            pos_str = f" (#{hp}v#{ap})" if hp and ap else ""
            lines.append(f"     Form: {hf} vs {af}{pos_str}")

        if pick.get("reasoning"):
            lines.append(f"     {pick['reasoning']}")
        lines.append("")

    return "\n".join(lines)
