"""
Reasoning Layer — Generates human-readable explanations for decisions.
Template-driven with dynamic variable injection. No external model calls.
"""

import random
from dataclasses import dataclass

from .slip_parser import Pick
from .strategy_engine import StrategyResult
from .risk_engine import PickRisk
from .decision_engine import PickDecision
from .replacement_engine import Replacement
from .rebuild_engine import OptimizedSlip


@dataclass
class ReasoningOutput:
    """All explanation strings for the full analysis."""
    strategy_explanation: str
    pick_explanations: list[dict]  # {pick, action, explanation}
    slip_insights: list[str]
    final_verdict: str


def generate_reasoning(
    decisions: list[PickDecision],
    replacements: list[Replacement],
    strategy: StrategyResult,
    optimized: OptimizedSlip,
) -> ReasoningOutput:
    """
    Generate all explanations from Layer 1 output.
    """
    strategy_exp = _explain_strategy(strategy)
    pick_exps = _explain_picks(decisions, replacements)
    slip_insights = _explain_slip_insights(optimized, strategy)
    verdict = _generate_verdict(optimized, strategy, decisions)

    return ReasoningOutput(
        strategy_explanation=strategy_exp,
        pick_explanations=pick_exps,
        slip_insights=slip_insights,
        final_verdict=verdict,
    )


def _explain_strategy(s: StrategyResult) -> str:
    """Generate strategy explanation."""
    templates = {
        "SAFE": [
            "Your slip reads as a SAFE strategy — heavy on favorites, low variance. Smart if you're grinding steady returns.",
            "This is a conservative slip — most picks are short odds. Nothing wrong with that, but one upset kills the whole thing.",
            "Detecting a SAFE approach here. You're banking on favorites delivering. The math favors you, but don't get complacent.",
        ],
        "MODERATE": [
            "Your slip reads as MODERATE — balanced risk with a mix of safe and semi-risky picks. This is the sweet spot if executed well.",
            "MODERATE strategy detected. You've got some solid anchors and a couple of ambitious picks. Let's see if the balance holds.",
            "This is a MODERATE slip — not reckless, not boring. The key is whether your mid-range picks have genuine edge.",
        ],
        "RISKY": [
            "Your slip reads as RISKY — high odds, speculative picks, big payout potential. Also big heartbreak potential.",
            "RISKY strategy detected. You're swinging for the fences. Let's make sure you're not swinging blind.",
            "This is an aggressive slip — most picks are above 2.5. The upside is real, but so is the downside.",
        ],
        "MIXED": [
            "Your slip is MIXED — no clear strategy. That's the most dangerous pattern because you get the risk of a risky slip with the payout of a safe one.",
            "MIXED strategy — some safe, some risky, no coherent plan. Let's tighten this up.",
            "This slip has no identity. Mixing safe and risky picks without a strategy usually means you get the worst of both worlds.",
        ],
    }

    options = templates.get(s.strategy, templates["MIXED"])
    return random.choice(options)


def _explain_picks(
    decisions: list[PickDecision],
    replacements: list[Replacement],
) -> list[dict]:
    """Generate per-pick explanations."""
    explanations = []
    replacement_map = {r.original.raw_line: r for r in replacements}

    for d in decisions:
        exp = _explain_single_pick(d, replacement_map.get(d.pick.raw_line))
        explanations.append({
            "pick": d.pick,
            "action": d.action,
            "explanation": exp,
        })

    return explanations


def _explain_single_pick(d: PickDecision, replacement: Replacement | None) -> str:
    """Generate explanation for a single pick decision."""
    pick = d.pick
    risk = d.risk

    if d.action == "KEEP":
        return _keep_explanation(pick, risk)
    elif d.action == "SWAP":
        return _swap_explanation(pick, risk, replacement)
    elif d.action == "REMOVE":
        return _remove_explanation(pick, risk)
    return d.reason


def _keep_explanation(pick: Pick, risk: PickRisk) -> str:
    """Generate KEEP explanation."""
    templates = [
        f"Solid pick. {pick.match_name} at {pick.odds:.2f} is {risk.risk_label.lower()} risk — this is your anchor.",
        f"Keep it. {pick.odds:.2f} with {risk.risk_label.lower()} risk — no reason to overthink this one.",
        f"This is fine. {pick.match_name} at {pick.odds:.2f} carries its weight in the slip.",
        f"Good value at {pick.odds:.2f}. {risk.risk_label} risk is acceptable here.",
    ]
    return random.choice(templates)


def _swap_explanation(pick: Pick, risk: PickRisk, replacement: Replacement | None) -> str:
    """Generate SWAP explanation."""
    if replacement:
        return (
            f"Close, but not worth the risk. Swapping {pick.bet_type} at {pick.odds:.2f} "
            f"for {replacement.new_bet_type} at {replacement.new_odds:.2f}. "
            f"{replacement.reason}."
        )
    return f"Swapping this one — {pick.odds:.2f} is too rich for what you're trying to do here."


def _remove_explanation(pick: Pick, risk: PickRisk) -> str:
    """Generate REMOVE explanation."""
    if risk.risk_label == "EXTREME":
        return f"Cut this. {pick.odds:.2f} with EXTREME risk — no replacement needed, your other picks carry the load."
    if pick.odds > 4.0:
        return f"{pick.odds:.2f} is a lottery ticket. Remove it entirely — no safe replacement exists at this level."
    templates = [
        f"Remove. {pick.match_name} at {pick.odds:.2f} is dragging your slip down.",
        f"Cut it. {risk.risk_label} risk at {pick.odds:.2f} doesn't justify the upside.",
        f"Gone. This pick is dead weight — your optimized slip is stronger without it.",
    ]
    return random.choice(templates)


def _explain_slip_insights(optimized: OptimizedSlip, strategy: StrategyResult) -> list[str]:
    """Generate slip-level insights."""
    insights = []

    # Odds insight
    if optimized.original_odds > 0:
        if optimized.total_odds < optimized.original_odds:
            insights.append(
                f"Total odds dropped from {optimized.original_odds:.2f}x to {optimized.total_odds:.2f}x — "
                f"you're trading payout for consistency."
            )
        else:
            insights.append(
                f"Total odds moved from {optimized.original_odds:.2f}x to {optimized.total_odds:.2f}x."
            )

    # Probability insight
    if optimized.original_prob > 0:
        if optimized.estimated_win_prob > optimized.original_prob:
            insights.append(
                f"Win probability went from {optimized.original_prob:.1f}% to {optimized.estimated_win_prob:.1f}% — "
                f"that's a real improvement."
            )

    # Risk profile insight
    insights.append(
        f"Your optimized slip has {optimized.pick_count} picks at {optimized.total_odds:.2f}x combined odds."
    )

    return insights


def _generate_verdict(
    optimized: OptimizedSlip,
    strategy: StrategyResult,
    decisions: list[PickDecision],
) -> str:
    """Generate the final verdict (2-3 sentences)."""
    swap_count = sum(1 for d in decisions if d.action == "SWAP")
    remove_count = sum(1 for d in decisions if d.action == "REMOVE")
    keep_count = sum(1 for d in decisions if d.action == "KEEP")

    parts = []

    if remove_count > 0 and swap_count > 0:
        parts.append(
            f"I removed {remove_count} pick{'s' if remove_count > 1 else ''} and swapped {swap_count}. "
            f"Your original slip had blind spots."
        )
    elif swap_count > 0:
        parts.append(
            f"I swapped {swap_count} pick{'s' if swap_count > 1 else ''} to tighten the slip. "
            f"Small changes, big difference."
        )
    elif keep_count == len(decisions):
        parts.append("Your slip was already tight — I just flagged the riskiest leg for awareness.")

    if optimized.estimated_win_prob < 5:
        parts.append("Even optimized, this is a long shot. Manage your stake accordingly.")
    elif optimized.estimated_win_prob < 15:
        parts.append("Decent probability for an accumulator. Don't overbet — the math is in your favor but not by much.")
    elif optimized.estimated_win_prob < 30:
        parts.append("This has a real shot. Stake responsibly but this isn't a Hail Mary.")
    else:
        parts.append("Strong probability. This is the kind of slip that can run consistently.")

    parts.append(f"Total: {optimized.total_odds:.2f}x | Est. win rate: {optimized.estimated_win_prob:.1f}%.")

    return " ".join(parts)
