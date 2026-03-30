"""
Decision Engine — Assigns KEEP / SWAP / REMOVE to each pick.
Enforces the "no universal KEEP" rule.
"""

from dataclasses import dataclass

from .config import DECISION, BET_TYPE_ALIASES
from .slip_parser import Pick
from .strategy_engine import StrategyResult
from .risk_engine import PickRisk


@dataclass
class PickDecision:
    """A pick with its assigned action."""
    pick: Pick
    risk: PickRisk
    action: str  # KEEP, SWAP, REMOVE
    reason: str  # human-readable reason for the decision


def make_decisions(
    picks: list[Pick],
    risks: list[PickRisk],
    strategy: StrategyResult,
) -> list[PickDecision]:
    """
    Assign KEEP / SWAP / REMOVE to each pick based on strategy and risk.

    Enforces: minimum 1 pick must be flagged (SWAP or REMOVE).
    """
    if not picks:
        return []

    thresholds = _get_thresholds(strategy.strategy)
    decisions = []

    for pick, risk in zip(picks, risks):
        action, reason = _evaluate_pick(pick, risk, strategy.strategy, thresholds)
        decisions.append(PickDecision(
            pick=pick,
            risk=risk,
            action=action,
            reason=reason,
        ))

    # Enforce minimum flags rule
    decisions = _enforce_min_flags(decisions, strategy.strategy)

    return decisions


def _get_thresholds(strategy: str):
    """Get decision thresholds for the given strategy."""
    mapping = {
        "SAFE": DECISION,
        "MODERME": DECISION,  # fallback
        "MODERATE": DECISION,
        "RISKY": DECISION,
        "MIXED": DECISION,
    }
    return mapping.get(strategy, DECISION)


def _evaluate_pick(
    pick: Pick,
    risk: PickRisk,
    strategy: str,
    thresholds,
) -> tuple[str, str]:
    """Evaluate a single pick and return (action, reason)."""
    bt = _normalize_bet_type(pick.bet_type)
    odds = pick.odds
    risk_label = risk.risk_label

    # Strategy-specific thresholds
    swap_odds, remove_odds, swap_risk, remove_risk = _get_strategy_limits(strategy)

    # REMOVE conditions (worst first)
    if odds > remove_odds:
        return "REMOVE", f"Odds of {odds:.2f} are too high for a {strategy.lower()} slip"

    if risk_label == "EXTREME" and strategy in ("SAFE", "MODERATE"):
        return "REMOVE", f"EXTREME risk on a {strategy.lower()} slip — cut it"

    if risk_label == "EXTREME" and strategy == "RISKY":
        return "REMOVE", f"Even for a risky slip, {odds:.2f} with {risk_label} risk is too much"

    if bt == "correct_score":
        return "REMOVE", "Correct score bets are lotteries — no edge here"

    if bt == "first_goalscorer":
        return "REMOVE", "First goalscorer is pure luck — cut it"

    # SWAP conditions
    if odds > swap_odds:
        safer = _suggest_safer_bet(bt, odds)
        return "SWAP", f"{odds:.2f} is above the {swap_odds:.1f} ceiling for {strategy.lower()} — swap to {safer}"

    if risk_label == swap_risk:
        safer = _suggest_safer_bet(bt, odds)
        return "SWAP", f"{risk_label} risk from {bt} at {odds:.2f} — swapping to {safer}"

    if bt == "X" and strategy == "SAFE":
        return "SWAP", "Draws are coin flips — Double Chance is safer"

    if bt in ("over_2.5", "over_3.5", "over_4.5") and strategy == "SAFE":
        return "SWAP", f"{bt} is too volatile for a safe slip — Over 1.5 is more reliable"

    if bt in ("btts_yes", "gg") and risk.risk_score > 50 and strategy == "SAFE":
        return "SWAP", "BTTS on a safe slip is asking for trouble — swap to goals market"

    # KEEP
    return "KEEP", _keep_reason(pick, risk, strategy)


def _get_strategy_limits(strategy: str) -> tuple[float, float, str, str]:
    """Return (swap_odds, remove_odds, swap_risk, remove_risk) for a strategy."""
    if strategy == "SAFE":
        return 2.5, 4.5, "HIGH", "EXTREME"
    elif strategy == "MODERATE":
        return 3.5, 5.5, "EXTREME", "EXTREME"
    elif strategy == "RISKY":
        return 5.0, 8.0, "EXTREME", "EXTREME"
    else:  # MIXED
        return 3.0, 5.0, "HIGH", "EXTREME"


def _suggest_safer_bet(bet_type: str, current_odds: float) -> str:
    """Suggest a safer alternative bet type."""
    mapping = {
        "X": "Double Chance (1X/X2)",
        "draw": "Double Chance (1X/X2)",
        "over_2.5": "Over 1.5 Goals",
        "over_3.5": "Over 2.5 Goals",
        "over_4.5": "Over 2.5 Goals",
        "btts_yes": "Over 1.5 Goals",
        "gg": "Over 1.5 Goals",
        "correct_score": "Over 1.5 Goals",
        "first_goalscorer": "Anytime Goalscorer",
        "ht_ft": "Match Winner",
        "handicap_away": "Double Chance (X2)",
    }
    return mapping.get(bet_type, "Double Chance or Over 1.5")


def _keep_reason(pick: Pick, risk: PickRisk, strategy: str) -> str:
    """Generate a KEEP reason."""
    if risk.risk_label == "LOW":
        return f"Low risk at {pick.odds:.2f} — solid foundation pick"
    if risk.risk_label == "MEDIUM":
        return f"Acceptable risk at {pick.odds:.2f} — fits the {strategy.lower()} profile"
    return f"At {pick.odds:.2f} this is tight but within tolerance for {strategy.lower()}"


def _enforce_min_flags(decisions: list[PickDecision], strategy: str) -> list[PickDecision]:
    """
    Ensure at least 1 pick is SWAP or REMOVE.
    If all are KEEP, flag the riskiest one as SWAP.
    """
    flagged = [d for d in decisions if d.action != "KEEP"]

    if len(flagged) >= DECISION.min_flags:
        return decisions

    # Find the riskiest KEEP pick
    keepers = [(i, d) for i, d in enumerate(decisions) if d.action == "KEEP"]
    if not keepers:
        return decisions

    keepers.sort(key=lambda x: x[1].risk.risk_score, reverse=True)
    idx, riskiest = keepers[0]

    decisions[idx] = PickDecision(
        pick=riskiest.pick,
        risk=riskiest.risk,
        action="SWAP",
        reason=f"Highest risk KEEP at {riskiest.risk.risk_score:.0f} — flagging for review to optimize your edge",
    )

    return decisions


def _normalize_bet_type(bet_type: str) -> str:
    cleaned = bet_type.lower().strip()
    return BET_TYPE_ALIASES.get(cleaned, cleaned)
