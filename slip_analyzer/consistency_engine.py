"""
Consistency Scoring Engine — Multi-factor model for scoring each pick.
Base probability + penalties + bonuses = consistency score (0-100).
"""

import math
from dataclasses import dataclass

from .config import PENALTIES, BONUSES, CONSISTENCY, BET_TYPE_BASELINE_PROB, BET_TYPE_ALIASES, DERBY_PAIRS
from .slip_parser import Pick


@dataclass
class PickScore:
    """Consistency score for a single pick."""
    pick: Pick
    base_prob: float
    penalties: list[str]
    penalty_total: int
    bonuses: list[str]
    bonus_total: int
    consistency_score: int
    classification: str  # Elite, Strong, Solid, Risky, Unreliable
    is_viable: bool


def score_all_picks(picks: list[Pick]) -> list[PickScore]:
    """Score all picks using the multi-factor consistency model."""
    return [_score_single(pick, i, len(picks)) for i, pick in enumerate(picks)]


def _score_single(pick: Pick, index: int, total: int) -> PickScore:
    """Score a single pick."""
    bt = _normalize_bet_type(pick.bet_type)
    odds = pick.odds

    # Base probability from bet type baseline
    base = BET_TYPE_BASELINE_PROB.get(bt, 50.0)

    # Adjust base by odds (higher odds = lower probability)
    if odds > 0:
        implied = 100.0 / odds
        # Blend baseline with implied probability
        base = (base * 0.4 + implied * 0.6)
    base = max(5.0, min(95.0, base))

    # Apply penalties
    penalties_applied = []
    penalty_total = 0

    if bt in ("X", "draw"):
        penalties_applied.append(f"Draw penalty ({PENALTIES.draw_penalty})")
        penalty_total += PENALTIES.draw_penalty

    if odds > 1.80:
        penalties_applied.append(f"High odds penalty ({PENALTIES.high_odds_penalty})")
        penalty_total += PENALTIES.high_odds_penalty

    if "HCP" in bt and ("H15" in bt or "H10" in bt or "A15" in bt):
        penalties_applied.append(f"Handicap aggression ({PENALTIES.handicap_aggression})")
        penalty_total += PENALTIES.handicap_aggression

    # Position penalty (later picks in acca compound risk)
    if total > 1 and index >= total - 2:
        penalties_applied.append(f"Acca tail position (-5)")
        penalty_total -= 5

    # Apply bonuses
    bonuses_applied = []
    bonus_total = 0

    if odds <= 1.35:
        bonuses_applied.append(f"Low odds value (+{BONUSES.low_odds_value})")
        bonus_total += BONUSES.low_odds_value

    if bt in ("O0.5", "O1.5", "12", "1X", "X2"):
        bonuses_applied.append(f"High-probability market (+3)")
        bonus_total += 3

    # Calculate final score
    score = int(max(0, min(100, base + penalty_total + bonus_total)))

    # Classify
    if score >= CONSISTENCY.elite_min:
        classification = "Elite"
    elif score >= CONSISTENCY.strong_min:
        classification = "Strong"
    elif score >= CONSISTENCY.solid_min:
        classification = "Solid"
    elif score >= CONSISTENCY.risky_min:
        classification = "Risky"
    else:
        classification = "Unreliable"

    return PickScore(
        pick=pick,
        base_prob=round(base, 1),
        penalties=penalties_applied,
        penalty_total=penalty_total,
        bonuses=bonuses_applied,
        bonus_total=bonus_total,
        consistency_score=score,
        classification=classification,
        is_viable=score >= CONSISTENCY.min_viable_score,
    )


def _normalize_bet_type(bt: str) -> str:
    return BET_TYPE_ALIASES.get(bt.lower().strip(), bt.lower().strip())
