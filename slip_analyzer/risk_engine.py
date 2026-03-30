"""
Risk Scoring Engine — Assigns a risk label to each individual pick.
"""

from dataclasses import dataclass

from .config import RISK, RISK_THRESH, BET_TYPE_RISK, BET_TYPE_ALIASES
from .slip_parser import Pick


@dataclass
class PickRisk:
    """Risk assessment for a single pick."""
    pick: Pick
    risk_score: float  # 0-100 composite score
    risk_label: str  # LOW, MEDIUM, HIGH, EXTREME
    factors: dict  # breakdown of scoring factors


def score_picks(picks: list[Pick]) -> list[PickRisk]:
    """
    Score risk for each pick in the slip.

    Returns list of PickRisk in the same order as input picks.
    """
    results = []
    total = len(picks)

    for i, pick in enumerate(picks):
        risk = _score_single_pick(pick, i, total)
        results.append(risk)

    return results


def _score_single_pick(pick: Pick, index: int, total_picks: int) -> PickRisk:
    """Calculate composite risk score for a single pick."""
    # Factor 1: Odds-based score (higher odds = higher risk)
    odds_score = min(_odds_to_risk(pick.odds), 100.0)

    # Factor 2: Bet type risk
    bt = _normalize_bet_type(pick.bet_type)
    bet_type_score = BET_TYPE_RISK.get(bt, BET_TYPE_RISK.get("unknown", 50.0))

    # Factor 3: Position risk (later picks compound risk)
    if total_picks > 1:
        position_score = (index / (total_picks - 1)) * 40.0  # 0 to 40
    else:
        position_score = 0.0

    # Factor 4: Implied probability inverse
    if pick.odds > 0:
        implied_prob = 1.0 / pick.odds
        implied_risk = (1.0 - implied_prob) * 100.0
    else:
        implied_risk = 100.0

    # Composite score
    composite = (
        odds_score * RISK.odds_weight
        + bet_type_score * RISK.bet_type_weight
        + position_score * RISK.position_weight
        + implied_risk * RISK.implied_prob_weight
    )

    # Clamp to 0-100
    composite = max(0.0, min(100.0, composite))

    # Assign label
    if composite <= RISK_THRESH.low_max:
        label = "LOW"
    elif composite <= RISK_THRESH.medium_max:
        label = "MEDIUM"
    elif composite <= RISK_THRESH.high_max:
        label = "HIGH"
    else:
        label = "EXTREME"

    factors = {
        "odds_score": round(odds_score, 1),
        "bet_type_score": round(bet_type_score, 1),
        "position_score": round(position_score, 1),
        "implied_risk": round(implied_risk, 1),
        "implied_probability": round(implied_prob * 100, 1) if pick.odds > 0 else 0,
    }

    return PickRisk(
        pick=pick,
        risk_score=round(composite, 1),
        risk_label=label,
        factors=factors,
    )


def _odds_to_risk(odds: float) -> float:
    """Convert odds to a 0-100 risk scale. 1.1 = very low risk, 10+ = very high."""
    if odds <= 1.0:
        return 0.0
    # Logarithmic scale: 1.1->5, 1.5->20, 2.0->35, 3.0->55, 5.0->72, 10.0->88, 20+->100
    import math
    log_odds = math.log(odds)
    # Normalize: ln(1.1)~0.1 -> ~5, ln(10)~2.3 -> ~90
    normalized = (log_odds / 3.0) * 100.0
    return max(0.0, min(100.0, normalized))


def _normalize_bet_type(bet_type: str) -> str:
    """Normalize bet type to canonical form."""
    cleaned = bet_type.lower().strip()
    return BET_TYPE_ALIASES.get(cleaned, cleaned)
