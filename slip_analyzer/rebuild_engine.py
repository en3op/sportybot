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


# =============================================================================
# NEW: Target-odds-based criteria for 2-3x, 5-7x, 9-12x slip tiers
# =============================================================================

# Target combined odds per tier
SAFE_TARGET_ODDS = (2.0, 3.5)      # 2-3x combined
MODERATE_TARGET_ODDS = (4.5, 8.0)  # 5-7x combined  
HIGH_TARGET_ODDS = (8.0, 15.0)     # 9-12x combined

# Preferred markets per tier
SAFE_MARKETS = ["Handicap", "Double Chance", "Goals", "DNB"]  # Safest markets
MODERATE_MARKETS = ["1X2", "BTTS", "Goals"]                    # Balanced markets
HIGH_MARKETS = ["1X2"]                                          # Straight results for max odds


def _safe_criteria_target(plays: list[dict], current_odds: float = 1.0, target_min: float = 2.0, target_max: float = 3.5) -> dict | None:
    """
    Pick a play that contributes to SAFE target odds (2-3x combined).
    
    Prefers: Handicap, Double Chance, Over 1.5, DNB
    Target: Each pick ~1.15-1.40 odds
    """
    # Preferred odds range for safe picks
    min_odds = max(1.10, target_min / max(current_odds, 1.0) ** 0.5)
    max_odds = min(1.80, target_max / max(current_odds, 1.0))
    
    # Filter by odds range
    eligible = [p for p in plays if min_odds <= p["odds"] <= max_odds]
    
    if not eligible:
        # Fallback: lowest odds
        eligible = sorted(plays, key=lambda p: p["odds"])
        return eligible[0] if eligible else None
    
    # Prefer safe markets
    preferred = [p for p in eligible if p.get("market") in SAFE_MARKETS]
    pool = preferred if preferred else eligible
    
    # Sort by implied probability (highest = safest)
    pool.sort(key=lambda p: p.get("implied", 0), reverse=True)
    
    return pool[0]


def _moderate_criteria_target(plays: list[dict], current_odds: float = 1.0, target_min: float = 4.5, target_max: float = 8.0) -> dict | None:
    """
    Pick a play that contributes to MODERATE target odds (5-7x combined).
    
    Prefers: 1X2 favorites, BTTS, Over 2.5
    Target: Each pick ~1.50-2.50 odds
    """
    # Calculate odds range needed
    min_odds = max(1.30, target_min / max(current_odds, 1.0) ** 0.33)
    max_odds = min(3.00, target_max / max(current_odds, 1.0))
    
    # Filter by odds range
    eligible = [p for p in plays if min_odds <= p["odds"] <= max_odds]
    
    if not eligible:
        # Fallback: expand range
        eligible = [p for p in plays if 1.20 <= p["odds"] <= 3.50]
        if not eligible:
            eligible = sorted(plays, key=lambda p: p["odds"])
            return eligible[0] if eligible else None
    
    # Prefer moderate markets
    preferred = [p for p in eligible if p.get("market") in MODERATE_MARKETS]
    pool = preferred if preferred else eligible
    
    # Sort by score (best value)
    pool.sort(key=lambda p: p.get("score", 0), reverse=True)
    
    return pool[0]


def _high_criteria_target(plays: list[dict], current_odds: float = 1.0, target_min: float = 8.0, target_max: float = 15.0) -> dict | None:
    """
    Pick a play that contributes to HIGH target odds (9-12x combined).
    
    Prefers: 1X2 underdogs, draws, away wins
    Target: Each pick ~2.00-5.00 odds
    """
    # Calculate odds range needed
    min_odds = max(1.80, target_min / max(current_odds, 1.0) ** 0.33)
    max_odds = min(6.00, target_max / max(current_odds, 1.0))
    
    # Filter by odds range
    eligible = [p for p in plays if min_odds <= p["odds"] <= max_odds]
    
    if not eligible:
        # Fallback: highest odds available
        eligible = sorted(plays, key=lambda p: p["odds"], reverse=True)
        return eligible[0] if eligible else None
    
    # Prefer 1X2 straight results (away/draw)
    preferred = [p for p in eligible if p.get("market") == "1X2"]
    
    # Further prefer away and draw (higher odds)
    underdog = [p for p in preferred if "Away" in p.get("pick", "") or "Draw" in p.get("pick", "")]
    pool = underdog if underdog else (preferred if preferred else eligible)
    
    # Sort by odds (highest first)
    pool.sort(key=lambda p: p["odds"], reverse=True)
    
    return pool[0]


def build_three_slips_target_odds(match_plays: dict[str, list[dict]], match_tiers: dict = None) -> list:
    """
    Build SAFE, MODERATE, HIGH slips targeting specific combined odds.
    
    SAFE: 2-3x combined (safest markets)
    MODERATE: 5-7x combined (balanced value)
    HIGH: 9-12x combined (high risk/reward)
    
    Each tier picks DIFFERENT markets from the same matches.
    
    Args:
        match_plays: {match_key: [plays]} from SportyBet API
        match_tiers: Optional {match_key: tier} from classification
    
    Returns:
        List of 3 ConstructedSlip objects
    """
    if not match_plays:
        return []
    
    tier_configs = [
        ("SAFE", "🔒", SAFE_TARGET_ODDS, _safe_criteria_target, "3-5%", "Maximum safety — safest markets"),
        ("MODERATE", "⚖️", MODERATE_TARGET_ODDS, _moderate_criteria_target, "2-3%", "Best value — balanced risk"),
        ("HIGH", "🚀", HIGH_TARGET_ODDS, _high_criteria_target, "1%", "High reward — aggressive picks"),
    ]
    
    slips = []
    
    for name, emoji, target_range, criteria_fn, bankroll, philosophy in tier_configs:
        slip = _build_tier_target_odds(
            name, emoji, match_plays, criteria_fn, target_range,
            bankroll, philosophy, match_tiers
        )
        if slip:
            slips.append(slip)
    
    return slips


def _build_tier_target_odds(
    name: str,
    emoji: str,
    match_plays: dict[str, list[dict]],
    criteria_fn,
    target_range: tuple,
    bankroll: str,
    philosophy: str,
    match_tiers: dict = None
) -> 'ConstructedSlip | None':
    """
    Build a single slip tier targeting specific combined odds.
    Picks ONE market per match, different per tier.
    """
    selected = []
    current_odds = 1.0
    target_min, target_max = target_range
    match_keys_used = set()
    
    # Sort matches by tier (S/A/B/C) if available, prioritize higher tiers
    match_keys = list(match_plays.keys())
    if match_tiers:
        tier_order = {"S": 0, "A": 1, "B": 2, "C": 3}
        match_keys.sort(key=lambda k: tier_order.get(match_tiers.get(k, "C"), 3))
    
    for match_key in match_keys:
        plays = match_plays.get(match_key, [])
        if not plays or match_key in match_keys_used:
            continue
        
        # Check if we've reached max picks or exceeded target
        if len(selected) >= MAX_PICKS_PER_SLIP:
            break
        
        # Stop adding picks if we've reached target
        if current_odds >= target_max:
            break
        
        # Pick using target-aware criteria
        pick = criteria_fn(plays, current_odds, target_min, target_max)
        
        if pick:
            selected.append((match_key, pick))
            current_odds *= pick["odds"]
            match_keys_used.add(match_key)
    
    if len(selected) < 2:
        return None
    
    # Build slip picks
    slip_picks = []
    for match_key, play in selected:
        implied = play.get("implied", 0)
        tier = match_tiers.get(match_key, "C") if match_tiers else "C"
        
        slip_picks.append(SlipPick(
            match_name=match_key,
            bet_type=play.get("pick_short", ""),
            bet_label=play.get("pick", ""),
            odds=play["odds"],
            consistency_score=int(implied),
            base_prob=implied,
            penalties=[],
            bonuses=[f"Tier {tier}"],
            reason=_generate_target_reason(play, tier, name),
        ))
    
    # Calculate totals
    total_odds = functools.reduce(lambda x, y: x * y, [p.odds for p in slip_picks], 1.0)
    raw_prob = functools.reduce(lambda x, y: x * y, [min(p.base_prob / 100, 0.99) for p in slip_picks], 1.0)
    win_prob = raw_prob * CORRELATION_ADJUSTMENT * 100
    
    # Risk stars
    avg_implied = sum(p.base_prob for p in slip_picks) / len(slip_picks)
    if avg_implied >= 70:
        risk_stars = 1
    elif avg_implied >= 55:
        risk_stars = 2
    elif avg_implied >= 40:
        risk_stars = 3
    elif avg_implied >= 30:
        risk_stars = 4
    else:
        risk_stars = 5
    
    weakest = min(slip_picks, key=lambda p: p.base_prob)
    key_risk = f"Weakest: {weakest.match_name} ({weakest.base_prob:.0f}%)"
    
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


def _generate_target_reason(play: dict, tier: str, slip_name: str) -> str:
    """Generate reason for a target-odds pick."""
    implied = play.get("implied", 0)
    odds = play.get("odds", 0)
    market = play.get("market", "")
    
    parts = []
    
    if slip_name == "SAFE":
        if implied >= 80:
            parts.append(f"Very safe ({implied:.0f}% implied)")
        elif implied >= 70:
            parts.append(f"High confidence ({implied:.0f}%)")
        else:
            parts.append(f"Solid pick ({implied:.0f}%)")
        
        if market == "Handicap":
            parts.append("HCP coverage")
        elif market == "Double Chance":
            parts.append("covers 2 outcomes")
        elif "Over 1.5" in play.get("pick", ""):
            parts.append("low line")
    
    elif slip_name == "MODERATE":
        if implied >= 50:
            parts.append(f"Good value ({implied:.0f}% @ {odds:.2f})")
        else:
            parts.append(f"Balanced risk ({implied:.0f}% @ {odds:.2f})")
        
        if market == "1X2":
            parts.append("straight result")
        elif market == "BTTS":
            parts.append("scoring form")
    
    else:  # HIGH
        parts.append(f"High odds play ({odds:.2f}x)")
        if market == "1X2":
            parts.append("underdog value")
    
    tier_desc = {"S": "Premium", "A": "Quality", "B": "Standard", "C": "Risky"}.get(tier, "")
    if tier_desc:
        parts.append(f"[{tier}]")
    
    return " | ".join(parts)


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
