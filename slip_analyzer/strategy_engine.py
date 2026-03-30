"""
Strategy Detection Engine — Analyzes a full slip and classifies the user's intent.
"""

import statistics
from dataclasses import dataclass

from .config import STRATEGY, BET_TYPE_ALIASES
from .slip_parser import Pick


@dataclass
class StrategyResult:
    """Result of strategy detection."""
    strategy: str  # SAFE, MODERATE, RISKY, MIXED
    confidence: float  # 0-100 how confident the classification is
    avg_odds: float
    std_dev: float
    favorite_ratio: float
    details: dict


def detect_strategy(picks: list[Pick]) -> StrategyResult:
    """
    Analyze all picks and classify the slip's strategy.

    Returns StrategyResult with classification and supporting metrics.
    """
    if not picks:
        return StrategyResult("MIXED", 0.0, 0.0, 0.0, 0.0, {})

    odds = [p.odds for p in picks]
    avg = statistics.mean(odds)
    std = statistics.stdev(odds) if len(odds) > 1 else 0.0

    # Classify each pick
    safe_count = 0
    moderate_count = 0
    risky_count = 0
    draw_count = 0
    btts_count = 0
    over25_count = 0
    over35_count = 0

    for p in picks:
        bt = _normalize_bet_type(p.bet_type)

        if bt == "X" or bt == "draw":
            draw_count += 1
        if bt in ("btts_yes", "gg", "btts_no", "ng"):
            btts_count += 1
        if bt == "over_2.5":
            over25_count += 1
        if bt == "over_3.5":
            over35_count += 1

        if STRATEGY.safe_odds_min <= p.odds <= STRATEGY.safe_odds_max:
            safe_count += 1
        elif STRATEGY.moderate_odds_min <= p.odds <= STRATEGY.moderate_odds_max:
            moderate_count += 1
        else:
            risky_count += 1

    total = len(picks)
    safe_ratio = safe_count / total
    moderate_ratio = moderate_count / total
    risky_ratio = risky_count / total

    # Determine dominant strategy
    details = {
        "safe_count": safe_count,
        "moderate_count": moderate_count,
        "risky_count": risky_count,
        "draw_count": draw_count,
        "btts_count": btts_count,
        "over25_count": over25_count,
        "over35_count": over35_count,
        "total_legs": total,
    }

    # Classification logic
    if safe_ratio >= STRATEGY.dominant_ratio:
        strategy = "SAFE"
        confidence = safe_ratio * 100
    elif risky_ratio >= STRATEGY.dominant_ratio:
        strategy = "RISKY"
        confidence = risky_ratio * 100
    elif moderate_ratio >= STRATEGY.dominant_ratio:
        strategy = "MODERATE"
        confidence = moderate_ratio * 100
    elif safe_ratio >= 0.4 and risky_ratio < 0.3:
        strategy = "SAFE"
        confidence = safe_ratio * 80
    elif risky_ratio >= 0.4:
        strategy = "RISKY"
        confidence = risky_ratio * 80
    elif std < STRATEGY.mixed_std_dev_min and avg < 2.0:
        strategy = "SAFE"
        confidence = 60.0
    elif std < STRATEGY.mixed_std_dev_min and avg >= 2.5:
        strategy = "RISKY"
        confidence = 60.0
    else:
        strategy = "MIXED"
        confidence = max(40.0, 100.0 - std * 20)

    # Adjust for exotic bets in "safe" slips
    if strategy == "SAFE" and (draw_count > 0 or btts_count > 0 or over25_count > 0):
        confidence = max(confidence - 15, 40)

    return StrategyResult(
        strategy=strategy,
        confidence=round(confidence, 1),
        avg_odds=round(avg, 2),
        std_dev=round(std, 2),
        favorite_ratio=round(safe_ratio, 2),
        details=details,
    )


def _normalize_bet_type(bet_type: str) -> str:
    """Normalize a bet type string to canonical form."""
    cleaned = bet_type.lower().strip()
    return BET_TYPE_ALIASES.get(cleaned, cleaned)
