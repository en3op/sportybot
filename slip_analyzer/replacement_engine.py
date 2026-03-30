"""
Replacement Engine — Generates safer alternatives for SWAP decisions.
Uses deterministic mapping rules, no guesswork.
"""

from dataclasses import dataclass

from .config import REPLACEMENT_RULES, BET_TYPE_ALIASES
from .slip_parser import Pick
from .decision_engine import PickDecision


@dataclass
class Replacement:
    """A replacement pick for a SWAP decision."""
    original: Pick
    new_bet_type: str
    new_odds: float
    reason: str


def generate_replacements(decisions: list[PickDecision]) -> list[Replacement]:
    """
    For every SWAP decision, generate a specific safer alternative.

    Returns list of Replacement objects.
    """
    replacements = []

    for d in decisions:
        if d.action == "SWAP":
            replacement = _find_replacement(d.pick, d.risk.risk_label)
            if replacement:
                replacements.append(replacement)

    return replacements


def _find_replacement(pick: Pick, risk_label: str) -> Replacement | None:
    """Find the best replacement for a pick using the mapping table."""
    bt = _normalize_bet_type(pick.bet_type)

    # Search replacement rules in order
    for rule in REPLACEMENT_RULES:
        if _matches_pattern(bt, rule.original_pattern):
            new_odds = _estimate_new_odds(pick.odds, rule.odds_multiplier)
            return Replacement(
                original=pick,
                new_bet_type=rule.replacement,
                new_odds=round(new_odds, 2),
                reason=rule.reason,
            )

    # Fallback: generic safe replacement
    return _generic_replacement(pick, risk_label)


def _matches_pattern(bet_type: str, pattern: str) -> bool:
    """Check if a bet type matches a replacement rule pattern."""
    if bet_type == pattern:
        return True
    # Check if bet type contains the pattern
    if pattern in bet_type:
        return True
    # Check aliases
    normalized = BET_TYPE_ALIASES.get(bet_type, bet_type)
    return normalized == pattern


def _estimate_new_odds(current_odds: float, multiplier: float) -> float:
    """Estimate the new odds after applying a safer replacement."""
    new = current_odds * multiplier
    # Clamp to reasonable range
    return max(1.05, min(new, 5.0))


def _generic_replacement(pick: Pick, risk_label: str) -> Replacement:
    """Generate a generic safe replacement when no rule matches."""
    bt = _normalize_bet_type(pick.bet_type)

    # High odds -> Double Chance on favorite
    if pick.odds > 3.0:
        return Replacement(
            original=pick,
            new_bet_type="1X",
            new_odds=round(pick.odds * 0.4, 2),
            reason=f"At {pick.odds:.2f} this is too speculative — Double Chance is much safer",
        )

    # Draw bet
    if bt in ("X", "draw"):
        return Replacement(
            original=pick,
            new_bet_type="1X",
            new_odds=round(pick.odds * 0.55, 2),
            reason="Draws are unpredictable — Double Chance covers the draw AND the win",
        )

    # Goals over
    if "over" in bt:
        return Replacement(
            original=pick,
            new_bet_type="over_1.5",
            new_odds=round(pick.odds * 0.5, 2),
            reason="Dropping to Over 1.5 — far more consistent across all leagues",
        )

    # BTTS
    if bt in ("btts_yes", "gg"):
        return Replacement(
            original=pick,
            new_bet_type="over_1.5",
            new_odds=round(pick.odds * 0.6, 2),
            reason="BTTS is match-dependent — Over 1.5 just needs 2 goals from anyone",
        )

    # Default
    return Replacement(
        original=pick,
        new_bet_type="1X",
        new_odds=round(pick.odds * 0.5, 2),
        reason="Swapping to a safer market — Double Chance on the favorite",
    )


def _normalize_bet_type(bet_type: str) -> str:
    cleaned = bet_type.lower().strip()
    return BET_TYPE_ALIASES.get(cleaned, cleaned)
