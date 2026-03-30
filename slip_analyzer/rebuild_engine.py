"""
Rebuild Engine — Constructs SAFE/MODERATE/HIGH slip variations.
Phase 4 of the analytical framework.
"""

import functools
from dataclasses import dataclass, field

from .config import SAFE_SLIP, MODERATE_SLIP, HIGH_SLIP, SLIP_TIERS, MAX_PICKS_PER_SLIP, CORRELATION_ADJUSTMENT
from .slip_parser import Pick
from .consistency_engine import PickScore


@dataclass
class SlipPick:
    """A pick within a constructed slip."""
    match_name: str
    bet_type: str
    bet_label: str
    odds: float
    consistency_score: int
    base_prob: float
    penalties: list[str]
    bonuses: list[str]
    reason: str


@dataclass
class ConstructedSlip:
    """A fully constructed slip tier."""
    name: str
    emoji: str
    picks: list[SlipPick]
    total_odds: float
    win_probability: float
    risk_stars: int
    bankroll_pct: str
    philosophy: str
    key_risk: str
    pro_tip: str


# =============================================================================
# NEW: Build 3 slips from SportyBet API events
# =============================================================================


def build_three_slips_from_events(match_plays: dict[str, list[dict]]) -> list[ConstructedSlip]:
    """Build SAFE, MODERATE, and HIGH slips from per-match API market plays.

    Args:
        match_plays: {match_key: [list of scored plays from analyze_all_markets_full]}
                     Each play has: market, pick, pick_short, odds, implied, tier, score

    Returns:
        List of 3 ConstructedSlip objects (SAFE, MODERATE, HIGH).
    """
    if not match_plays:
        return []

    tier_configs = [
        ("SAFE",     "\U0001f512", _safe_criteria,   "3-5%", "Maximum win probability — safest markets from your games"),
        ("MODERATE", "\u2696\ufe0f", _moderate_criteria, "2-3%", "Balanced risk/reward — best value from your games"),
        ("HIGH",     "\U0001f680", _high_criteria,    "1-2%", "High reward — aggressive picks from your games"),
    ]

    slips = []
    for name, emoji, criteria_fn, bankroll, philosophy in tier_configs:
        slip = _build_tier_from_events(name, emoji, match_plays, criteria_fn, bankroll, philosophy)
        if slip:
            slips.append(slip)

    return slips


def _safe_criteria(plays: list[dict]) -> dict | None:
    """Pick the safest play: highest implied probability, odds <= 1.80."""
    eligible = [p for p in plays if p["odds"] <= 1.80 and p["implied"] >= 50]
    if not eligible:
        # Fallback: lowest odds available
        eligible = sorted(plays, key=lambda p: p["odds"])
        return eligible[0] if eligible else None
    # Sort by implied probability descending (safest first)
    eligible.sort(key=lambda p: p["implied"], reverse=True)
    return eligible[0]


def _moderate_criteria(plays: list[dict]) -> dict | None:
    """Pick moderate play: best value, odds 1.20-2.50, prefers 1X2 and goals markets."""
    eligible = [p for p in plays if 1.20 <= p["odds"] <= 2.50 and p["implied"] >= 35]
    if not eligible:
        eligible = [p for p in plays if p["odds"] <= 2.50]
    if not eligible:
        eligible = sorted(plays, key=lambda p: p["odds"])
        return eligible[0] if eligible else None
    # Prefer 1X2 and goals markets for moderate
    primary = [p for p in eligible if p.get("market") in ("1X2", "Goals", "BTTS")]
    pool = primary if primary else eligible
    pool.sort(key=lambda p: p["score"], reverse=True)
    return pool[0]


def _high_criteria(plays: list[dict]) -> dict | None:
    """Pick high-risk play: odds 2.00-6.00, prefers straight results and higher odds."""
    eligible = [p for p in plays if 2.00 <= p["odds"] <= 6.00]
    if not eligible:
        # Fallback: highest odds available
        eligible = sorted(plays, key=lambda p: p["odds"], reverse=True)
        return eligible[0] if eligible else None
    # Prefer 1X2 straight results for high risk
    primary = [p for p in eligible if p.get("market") == "1X2"]
    pool = primary if primary else eligible
    pool.sort(key=lambda p: p["odds"], reverse=True)
    return pool[0]


def _build_tier_from_events(
    name: str,
    emoji: str,
    match_plays: dict[str, list[dict]],
    criteria_fn,
    bankroll: str,
    philosophy: str,
) -> ConstructedSlip | None:
    """Build a single slip tier from per-match plays."""
    selected = []
    match_keys_used = set()

    for match_key, plays in match_plays.items():
        if not plays:
            continue
        if match_key in match_keys_used:
            continue
        if len(selected) >= MAX_PICKS_PER_SLIP:
            break

        pick = criteria_fn(plays)
        if pick:
            selected.append((match_key, pick))
            match_keys_used.add(match_key)

    if len(selected) < 2:
        return None

    # Build slip picks
    slip_picks = []
    for match_key, play in selected:
        implied = play.get("implied", 0)
        slip_picks.append(SlipPick(
            match_name=match_key,
            bet_type=play.get("pick_short", ""),
            bet_label=play.get("pick", ""),
            odds=play["odds"],
            consistency_score=int(implied),
            base_prob=implied,
            penalties=[],
            bonuses=[],
            reason=_generate_event_reason(play, name),
        ))

    # Calculate totals
    total_odds = functools.reduce(lambda x, y: x * y, [p.odds for p in slip_picks], 1.0)
    raw_prob = functools.reduce(lambda x, y: x * y, [min(p.base_prob / 100, 0.99) for p in slip_picks], 1.0)
    win_prob = raw_prob * CORRELATION_ADJUSTMENT * 100

    # Risk stars based on average implied probability
    avg_implied = sum(p.base_prob for p in slip_picks) / len(slip_picks)
    if avg_implied >= 70:
        risk_stars = 1
    elif avg_implied >= 55:
        risk_stars = 2
    elif avg_implied >= 45:
        risk_stars = 3
    elif avg_implied >= 35:
        risk_stars = 4
    else:
        risk_stars = 5

    # Key risk
    weakest = min(slip_picks, key=lambda p: p.base_prob)
    key_risk = f"Weakest leg: {weakest.match_name} ({weakest.base_prob:.0f}% implied)"

    pro_tip = _generate_pro_tip(name, len(slip_picks), total_odds, win_prob)

    return ConstructedSlip(
        name=name,
        emoji=emoji,
        picks=slip_picks,
        total_odds=round(total_odds, 2),
        win_probability=round(win_prob, 1),
        risk_stars=risk_stars,
        bankroll_pct=bankroll,
        philosophy=philosophy,
        key_risk=key_risk,
        pro_tip=pro_tip,
    )


def _generate_event_reason(play: dict, tier_name: str) -> str:
    """Generate a reason for a pick from API data."""
    implied = play.get("implied", 0)
    odds = play.get("odds", 0)
    market = play.get("market", "")
    pick = play.get("pick", "")

    parts = []
    if implied >= 70:
        parts.append(f"High-confidence pick: {implied:.0f}% implied probability at {odds:.2f}.")
    elif implied >= 50:
        parts.append(f"Solid pick: {implied:.0f}% implied probability at {odds:.2f}.")
    else:
        parts.append(f"Value pick: {implied:.0f}% implied probability at {odds:.2f}.")

    if market == "Double Chance":
        parts.append("Covers two outcomes for extra safety.")
    elif market == "DNB":
        parts.append("Draw No Bet — stake returned if draw.")
    elif market == "Goals":
        parts.append("Goals market based on scoring patterns.")
    elif market == "BTTS":
        parts.append("Both teams have scoring form.")

    return " ".join(parts)


def build_three_slips(scores: list[PickScore]) -> list[ConstructedSlip]:
    """
    Build SAFE, MODERATE, and HIGH slips from scored picks.

    Rules:
    - Always use ALL picks (never reject based on score)
    - No duplicate matches within a slip
    - A match CAN appear in multiple slips with different markets
    - Never exceed MAX_PICKS_PER_SLIP
    """
    if not scores:
        return []

    # Sort by consistency score descending
    sorted_scores = sorted(scores, key=lambda s: s.consistency_score, reverse=True)

    slips = []
    for tier in SLIP_TIERS:
        slip = _build_single_slip(sorted_scores, tier)
        if slip:
            slips.append(slip)

    return slips


def _build_single_slip(all_scores: list[PickScore], tier) -> ConstructedSlip | None:
    """Build a single slip for the given tier."""
    # Filter picks that meet this tier's minimum score
    eligible = [s for s in all_scores if s.consistency_score >= tier.min_score]

    # Sort by score descending
    eligible.sort(key=lambda s: s.consistency_score, reverse=True)

    # Select picks respecting match uniqueness
    selected = []
    used_matches = set()

    for score in eligible:
        if len(selected) >= tier.pick_count[1]:
            break
        if score.pick.match_name in used_matches:
            continue
        # Check individual odds cap
        if score.pick.odds > tier.max_individual_odds:
            continue

        selected.append(score)
        used_matches.add(score.pick.match_name)

    # If not enough picks, relax odds constraint slightly
    if len(selected) < tier.pick_count[0]:
        for score in eligible:
            if len(selected) >= tier.pick_count[0]:
                break
            if score.pick.match_name in used_matches:
                continue
            if score.pick.odds <= tier.max_individual_odds + 0.3:
                selected.append(score)
                used_matches.add(score.pick.match_name)

    if len(selected) < tier.pick_count[0]:
        # Not enough quality picks for this tier
        return None

    # Build slip picks
    slip_picks = []
    for s in selected:
        slip_picks.append(SlipPick(
            match_name=s.pick.match_name,
            bet_type=s.pick.bet_type,
            bet_label=s.pick.bet_type,
            odds=s.pick.odds,
            consistency_score=s.consistency_score,
            base_prob=s.base_prob,
            penalties=s.penalties,
            bonuses=s.bonuses,
            reason=_generate_reason(s, tier.name),
        ))

    # Calculate totals
    total_odds = functools.reduce(lambda x, y: x * y, [p.odds for p in slip_picks], 1.0)
    raw_prob = functools.reduce(lambda x, y: x * y, [min(p.base_prob / 100, 0.99) for p in slip_picks], 1.0)
    win_prob = raw_prob * CORRELATION_ADJUSTMENT * 100

    # Risk stars
    avg_score = sum(s.consistency_score for s in selected) / len(selected)
    if avg_score >= 80:
        risk_stars = 1
    elif avg_score >= 70:
        risk_stars = 2
    elif avg_score >= 60:
        risk_stars = 3
    elif avg_score >= 50:
        risk_stars = 4
    else:
        risk_stars = 5

    # Key risk factor
    weakest = min(selected, key=lambda s: s.consistency_score)
    key_risk = f"Weakest leg: {weakest.pick.match_name} ({weakest.consistency_score}/100)"

    # Pro tip
    pro_tip = _generate_pro_tip(tier.name, len(slip_picks), total_odds, win_prob)

    return ConstructedSlip(
        name=tier.name,
        emoji=tier.emoji,
        picks=slip_picks,
        total_odds=round(total_odds, 2),
        win_probability=round(win_prob, 1),
        risk_stars=risk_stars,
        bankroll_pct=tier.bankroll_pct,
        philosophy=tier.philosophy,
        key_risk=key_risk,
        pro_tip=pro_tip,
    )


def _generate_reason(score: PickScore, tier_name: str) -> str:
    """Generate a 2-3 sentence reason for the pick."""
    pick = score.pick
    bt = pick.bet_type

    parts = []

    if score.consistency_score >= 80:
        parts.append(f"Elite-tier pick at {pick.odds:.2f} with {score.base_prob:.0f}% base probability.")
    elif score.consistency_score >= 70:
        parts.append(f"Strong pick at {pick.odds:.2f} — {score.base_prob:.0f}% base probability.")
    else:
        parts.append(f"Solid pick at {pick.odds:.2f} with {score.base_prob:.0f}% probability.")

    if "DNB" in bt or "1X" in bt or "X2" in bt or "12" in bt:
        parts.append("Double Chance/DNB provides a safety net on this result.")
    elif "O" in bt:
        parts.append("Goals market selected based on typical scoring patterns.")
    elif bt in ("1", "2"):
        parts.append("Straight result pick backed by form differential.")

    if score.penalties:
        parts.append(f"Note: {score.penalties[0].split('(')[0].strip()} applies.")
    if score.bonuses:
        parts.append(f"{score.bonuses[0].split('(')[0].strip()} supports this selection.")

    return " ".join(parts)


def _generate_pro_tip(tier_name: str, pick_count: int, total_odds: float, win_prob: float) -> str:
    """Generate a pro tip for the slip."""
    if tier_name == "SAFE":
        if win_prob > 25:
            return "This slip is ideal for flat staking — consistent returns without chasing."
        return "High probability but moderate payout. Consider a slightly higher stake to maximize returns."
    elif tier_name == "MODERATE":
        return "Smart value with a safety net. If the first 3 picks land, consider partial cashout on the final picks."
    else:
        if total_odds > 4.0:
            return "High reward potential but higher variance. Stake conservatively (1-2% of bankroll)."
        return "Calculated aggression — good risk/reward ratio for this tier."
