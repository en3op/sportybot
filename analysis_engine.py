#!/usr/bin/env python3
"""
Intent-Aware Betting Slip Analyzer
Author: Sharp Betting Analyst Engine v2.0
"""

from __future__ import annotations
import math
import statistics
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Strategy(Enum):
    SAFE = "SAFE"
    MODERATE = "MODERATE"
    RISKY = "RISKY"
    MIXED = "MIXED"


class RiskLevel(Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"
    EXTREME = "Extreme"


class SlipType(Enum):
    SAFE_STACK = "Safe Stack"
    BALANCED_BUILDER = "Balanced Builder"
    HIGH_RISK_ACCUMULATOR = "High-Risk Accumulator"
    LOTTERY_TICKET = "Lottery Ticket"


class Recommendation(Enum):
    KEEP = "Keep"
    SWAP = "Swap"
    REMOVE = "Remove"


@dataclass
class Pick:
    home_team: str
    away_team: str
    selection: str
    odds: float
    league: str = ""
    match_time: str = ""
    notes: str = ""


@dataclass
class PickAnalysis:
    pick: Pick
    fits_strategy: bool
    risk_level: RiskLevel
    insight: str
    recommendation: Recommendation
    alternative_suggestion: Optional[str] = None


@dataclass
class SlipAnalysis:
    picks: list[Pick]
    strategy: Strategy
    strategy_explanation: str
    pick_analyses: list[PickAnalysis]
    total_odds: float
    realistic_probability: float
    slip_type: SlipType
    slip_explanation: str
    final_summary: str


RISKY_SELECTION_KEYWORDS: list[str] = [
    "draw", "correct score", "half-time/full-time",
    "btts", "both teams to score",
    "over 3.5", "over 4.5", "over 5.5",
    "under 0.5", "under 1.5",
    "first goalscorer", "anytime goalscorer",
    "handicap", "-1", "+1", "-2", "+2",
    "win to nil", "clean sheet",
    "red card", "penalty",
]

MODERATE_SELECTION_KEYWORDS: list[str] = [
    "over 2.5", "under 2.5",
    "away win", "home win",
    "double chance",
    "half-time", "second half",
]

SAFE_SELECTION_KEYWORDS: list[str] = [
    "over 1.5", "under 4.5",
    "double chance",
    "favourite", "favorite",
    "no draw",
]


def classify_bet_risk(selection: str, odds: float) -> RiskLevel:
    """Classify a single bet's intrinsic risk from selection text + odds."""
    sel_lower = selection.lower().strip()

    if odds >= 5.0:
        base_risk = RiskLevel.EXTREME
    elif odds >= 3.5:
        base_risk = RiskLevel.HIGH
    elif odds >= 2.5:
        base_risk = RiskLevel.MODERATE
    elif odds >= 1.8:
        base_risk = RiskLevel.MODERATE
    else:
        base_risk = RiskLevel.LOW

    for keyword in RISKY_SELECTION_KEYWORDS:
        if keyword in sel_lower:
            if base_risk == RiskLevel.LOW:
                return RiskLevel.MODERATE
            if base_risk == RiskLevel.MODERATE:
                return RiskLevel.HIGH
            return RiskLevel.EXTREME

    for keyword in SAFE_SELECTION_KEYWORDS:
        if keyword in sel_lower:
            if base_risk == RiskLevel.EXTREME:
                return RiskLevel.HIGH
            if base_risk == RiskLevel.HIGH:
                return RiskLevel.MODERATE

    if sel_lower in ("draw", "x", "tie"):
        if base_risk in (RiskLevel.LOW, RiskLevel.MODERATE):
            return RiskLevel.HIGH
        return RiskLevel.EXTREME

    return base_risk


def detect_strategy(picks: list[Pick]) -> tuple[Strategy, str]:
    """Classify the user's overall strategy from the full slip."""
    if not picks:
        return Strategy.MIXED, "Empty slip - no strategy detected."

    odds = [p.odds for p in picks]
    risk_levels = [classify_bet_risk(p.selection, p.odds) for p in picks]

    avg_odds = statistics.mean(odds)
    max_odds = max(odds)
    min_odds = min(odds)
    num_picks = len(picks)

    risky_count = sum(
        1 for r in risk_levels
        if r in (RiskLevel.HIGH, RiskLevel.EXTREME)
    )
    safe_count = sum(1 for r in risk_levels if r == RiskLevel.LOW)
    moderate_count = len(risk_levels) - risky_count - safe_count

    risky_ratio = risky_count / num_picks
    safe_ratio = safe_count / num_picks

    if avg_odds <= 1.8 and risky_ratio == 0:
        return (
            Strategy.SAFE,
            f"Average odds {avg_odds:.2f} with {safe_count}/{num_picks} "
            f"low-risk picks. You're playing it very conservatively.",
        )

    if avg_odds >= 2.8 or risky_ratio >= 0.7:
        return (
            Strategy.RISKY,
            f"Average odds {avg_odds:.2f} with {risky_count}/{num_picks} "
            f"high-risk picks. You're swinging for the fences.",
        )

    spread = max_odds - min_odds
    if spread > 3.0 or (0.25 < risky_ratio < 0.6 and 0.2 < safe_ratio < 0.6):
        return (
            Strategy.MIXED,
            f"Odds spread {min_odds:.1f}-{max_odds:.1f} with a mix of "
            f"safe, moderate, and risky picks. Your strategy is inconsistent.",
        )

    return (
        Strategy.MODERATE,
        f"Average odds {avg_odds:.2f} with a balanced risk profile "
        f"({moderate_count}/{num_picks} moderate picks). "
        f"Solid middle-ground approach.",
    )


_ALTERNATIVE_MAP: dict[tuple[str, str], list[str]] = {
    ("SAFE", "HIGH"): [
        "Double Chance (1X or X2)",
        "Over 1.5 Goals",
        "Favourite to Win",
    ],
    ("SAFE", "EXTREME"): [
        "Double Chance (1X or X2)",
        "Over 1.5 Goals",
        "Remove entirely - doesn't fit your profile",
    ],
    ("MODERATE", "EXTREME"): [
        "Over 2.5 Goals if stats support it",
        "Home/Away Win at lower odds",
        "Draw No Bet",
    ],
    ("MODERATE", "LOW"): [
        "Over 2.5 Goals for better value",
        "Home Win instead of Double Chance",
    ],
    ("RISKY", "EXTREME"): [
        "Same market at slightly lower odds (5.0+ -> 2.5-3.5 range)",
        "BTTS + Over 2.5 combo instead of Correct Score",
        "Reduce stake or remove",
    ],
    ("RISKY", "LOW"): [
        "Over 2.5 Goals",
        "BTTS Yes",
        "Replace - it's diluting your high-odds slip",
    ],
}


def _generate_insight(
    pick: Pick,
    risk: RiskLevel,
    strategy: Strategy,
    fits: bool,
) -> str:
    """Generate a human-sounding insight for a single pick."""
    sel = pick.selection
    odds = pick.odds
    teams = f"{pick.home_team} vs {pick.away_team}"

    parts: list[str] = []

    if risk == RiskLevel.EXTREME:
        parts.append(
            f"At {odds:.2f}, this is a long shot. "
            f"Bookmakers are pricing in a low probability."
        )
    elif risk == RiskLevel.HIGH:
        parts.append(
            f"Sitting at {odds:.2f}, this carries real risk. "
            f"Not impossible, but far from a banker."
        )
    elif risk == RiskLevel.MODERATE:
        parts.append(
            f"At {odds:.2f}, this is a reasonable pick "
            f"but not a certainty by any means."
        )
    else:
        parts.append(
            f"At {odds:.2f}, the bookies see this as fairly likely."
        )

    if not fits:
        if strategy == Strategy.SAFE and risk in (RiskLevel.HIGH, RiskLevel.EXTREME):
            parts.append(
                "This pick contradicts your safe approach - it introduces "
                "unnecessary variance into an otherwise tight slip."
            )
        elif strategy == Strategy.RISKY and risk == RiskLevel.LOW:
            parts.append(
                "This pick is too safe for your high-odds strategy. "
                "It's dragging your potential payout down without meaningfully "
                "improving your win probability."
            )
        elif strategy == Strategy.MODERATE:
            parts.append(
                "This pick sits outside your moderate range - "
                "either too hot or too cold for the rest of your slip."
            )
        else:
            parts.append(
                "This pick doesn't align with the rest of your strategy."
            )

    sel_lower = sel.lower()
    if "draw" in sel_lower:
        parts.append(
            "Draws are notoriously hard to predict - even top analysts "
            "struggle to hit them consistently."
        )
    if "over 3.5" in sel_lower or "over 4.5" in sel_lower:
        parts.append(
            f"High goal lines like {sel} require a specific game script - "
            f"even attacking teams have quiet days."
        )
    if "btts" in sel_lower or "both teams" in sel_lower:
        parts.append(
            "BTTS depends on both teams showing up offensively. "
            "One bus-parking side kills this bet."
        )

    return " ".join(parts)


def _decide_recommendation(
    risk: RiskLevel,
    strategy: Strategy,
    fits: bool,
) -> Recommendation:
    """Decide Keep / Swap / Remove based on context."""
    if fits and risk != RiskLevel.EXTREME:
        return Recommendation.KEEP

    if risk == RiskLevel.EXTREME and strategy != Strategy.RISKY:
        return Recommendation.REMOVE

    if strategy == Strategy.RISKY and risk == RiskLevel.LOW:
        return Recommendation.SWAP

    if strategy == Strategy.SAFE and risk in (RiskLevel.HIGH, RiskLevel.EXTREME):
        return Recommendation.SWAP

    if not fits:
        return Recommendation.SWAP

    return Recommendation.KEEP


def _get_alternative(
    strategy: Strategy,
    risk: RiskLevel,
) -> Optional[str]:
    """Return a suggested alternative bet, if any."""
    key = (strategy.value, risk.value)
    alts = _ALTERNATIVE_MAP.get(key)
    if alts:
        return alts[0]
    return None


def analyze_single_pick(
    pick: Pick,
    strategy: Strategy,
) -> PickAnalysis:
    """Full analysis of one pick within the context of the user's strategy."""
    risk = classify_bet_risk(pick.selection, pick.odds)

    fits = True
    if strategy == Strategy.SAFE and risk in (RiskLevel.HIGH, RiskLevel.EXTREME):
        fits = False
    elif strategy == Strategy.RISKY and risk == RiskLevel.LOW:
        fits = False
    elif strategy == Strategy.MODERATE and risk == RiskLevel.EXTREME:
        fits = False

    insight = _generate_insight(pick, risk, strategy, fits)
    rec = _decide_recommendation(risk, strategy, fits)
    alt = _get_alternative(strategy, risk) if rec == Recommendation.SWAP else None

    return PickAnalysis(
        pick=pick,
        fits_strategy=fits,
        risk_level=risk,
        insight=insight,
        recommendation=rec,
        alternative_suggestion=alt,
    )


def _implied_probability(odds: float) -> float:
    """Convert decimal odds to implied probability (0-1)."""
    if odds <= 1.0:
        return 0.0
    return 1.0 / odds


def _realistic_slip_probability(picks: list[Pick]) -> float:
    """Estimate realistic probability of the full accumulator winning."""
    if not picks:
        return 0.0

    probs = [_implied_probability(p.odds) for p in picks]
    adjusted = [min(p * 1.05, 0.95) for p in probs]

    combined = 1.0
    for p in adjusted:
        combined *= p

    if len(picks) >= 7:
        combined *= 0.85
    elif len(picks) >= 5:
        combined *= 0.92

    return combined


def classify_slip_type(
    total_odds: float,
    num_picks: int,
    strategy: Strategy,
    probability: float,
) -> tuple[SlipType, str]:
    """Determine the accumulator archetype."""
    if total_odds < 3.0 and num_picks <= 3:
        return (
            SlipType.SAFE_STACK,
            f"At {total_odds:.2f} total odds with only {num_picks} picks, "
            f"this is a conservative build. "
            f"Estimated win chance: ~{probability * 100:.1f}%.",
        )

    if total_odds >= 50.0 or num_picks >= 7:
        return (
            SlipType.LOTTERY_TICKET,
            f"At {total_odds:.2f} total odds with {num_picks} picks, "
            f"this is essentially a lottery ticket. "
            f"Estimated win chance: ~{probability * 100:.1f}%. "
            f"Only play this with money you're 100% okay losing.",
        )

    if total_odds >= 15.0 or strategy == Strategy.RISKY:
        return (
            SlipType.HIGH_RISK_ACCUMULATOR,
            f"At {total_odds:.2f} total odds, this is a high-risk play. "
            f"Estimated win chance: ~{probability * 100:.1f}%. "
            f"Big upside, but expect to lose more often than you win.",
        )

    return (
        SlipType.BALANCED_BUILDER,
        f"At {total_odds:.2f} total odds with {num_picks} picks, "
        f"this is a balanced accumulator. "
        f"Estimated win chance: ~{probability * 100:.1f}%. "
        f"A reasonable approach if picks are well-researched.",
    )


def _generate_final_summary(
    strategy: Strategy,
    slip_type: SlipType,
    analyses: list[PickAnalysis],
    total_odds: float,
    probability: float,
    num_picks: int,
) -> str:
    """Generate the actionable final summary block."""
    problems: list[str] = []
    fixes: list[str] = []
    tips: list[str] = []

    remove_count = sum(
        1 for a in analyses if a.recommendation == Recommendation.REMOVE
    )
    swap_count = sum(
        1 for a in analyses if a.recommendation == Recommendation.SWAP
    )
    risky_picks = sum(
        1 for a in analyses
        if a.risk_level in (RiskLevel.HIGH, RiskLevel.EXTREME)
    )

    if strategy == Strategy.MIXED:
        problems.append(
            "You're mixing safe and risky picks, which destroys your edge. "
            "Safe picks lower your payout without significantly improving "
            "your win probability when combined with long shots."
        )

    if num_picks >= 7:
        problems.append(
            f"Your {num_picks}-pick slip is too long. "
            f"Every extra leg multiplies your chance of losing."
        )

    if remove_count >= 2:
        problems.append(
            f"{remove_count} picks are actively hurting your slip - "
            f"they're either too risky or completely misaligned."
        )

    if probability < 0.05:
        problems.append(
            f"Realistic win probability is around {probability * 100:.1f}%. "
            f"You're essentially donating to the bookmaker."
        )

    if not problems:
        problems.append("No major structural issues detected.")

    if strategy == Strategy.MIXED:
        safe_picks = [
            a for a in analyses
            if a.risk_level in (RiskLevel.LOW, RiskLevel.MODERATE)
        ]
        risky_picks_list = [
            a for a in analyses
            if a.risk_level in (RiskLevel.HIGH, RiskLevel.EXTREME)
        ]
        if safe_picks and risky_picks_list:
            fixes.append(
                f"Split into 2 slips:\n"
                f"   Safe slip ({len(safe_picks)} picks) - "
                f"low odds, higher hit rate\n"
                f"   Risky slip ({len(risky_picks_list)} picks) - "
                f"high odds, smaller stake"
            )

    if num_picks >= 7:
        fixes.append(
            f"Cut down to 3-5 picks maximum. "
            f"Quality over quantity wins in the long run."
        )

    if remove_count > 0:
        fixes.append(
            f"Remove the {remove_count} flagged pick(s) immediately."
        )

    if swap_count > 0:
        fixes.append(
            f"Swap the {swap_count} mismatched pick(s) for alternatives "
            f"suggested above."
        )

    if not fixes:
        fixes.append("Your slip is well-constructed. No major changes needed.")

    if total_odds > 20.0:
        tips.append(
            f"Consider reducing stake on slips above 20.0 odds. "
            f"Use them as fun side bets, not your main strategy."
        )

    if num_picks >= 5 and probability > 0.10:
        tips.append(
            "Your probability is decent for a long slip. "
            "Focus on research quality for each leg."
        )

    if strategy == Strategy.SAFE:
        tips.append(
            "Safe strategies work best with consistent staking. "
            "Bet the same amount every time and let volume do the work."
        )

    if strategy == Strategy.RISKY:
        tips.append(
            "High-risk bettors survive by staking small. "
            "Never put more than 1-2% of your bankroll on a risky acca."
        )

    tips.append(
        f"Expected value matters more than any single bet. "
        f"Track your results over 100+ bets to see if your strategy works."
    )

    sections: list[str] = []

    sections.append("Problem(s):")
    for p in problems:
        sections.append(f"  {p}")

    sections.append("")
    sections.append("Fix:")
    for f_item in fixes:
        sections.append(f"  {f_item}")

    sections.append("")
    sections.append("Pro Tip:")
    for t in tips:
        sections.append(f"  {t}")

    return "\n".join(sections)


def analyze_slip(picks: list[Pick]) -> SlipAnalysis:
    """Run the full intent-aware analysis pipeline on a betting slip."""
    strategy, strategy_explanation = detect_strategy(picks)
    pick_analyses = [analyze_single_pick(p, strategy) for p in picks]

    total_odds = 1.0
    for p in picks:
        total_odds *= p.odds

    probability = _realistic_slip_probability(picks)

    slip_type, slip_explanation = classify_slip_type(
        total_odds, len(picks), strategy, probability
    )

    final_summary = _generate_final_summary(
        strategy, slip_type, pick_analyses,
        total_odds, probability, len(picks),
    )

    return SlipAnalysis(
        picks=picks,
        strategy=strategy,
        strategy_explanation=strategy_explanation,
        pick_analyses=pick_analyses,
        total_odds=total_odds,
        realistic_probability=probability,
        slip_type=slip_type,
        slip_explanation=slip_explanation,
        final_summary=final_summary,
    )


_STRATEGY_EMOJI = {
    Strategy.SAFE: "SAFE",
    Strategy.MODERATE: "BALANCED",
    Strategy.RISKY: "RISKY",
    Strategy.MIXED: "MIXED",
}

_RISK_EMOJI = {
    RiskLevel.LOW: "LOW",
    RiskLevel.MODERATE: "MED",
    RiskLevel.HIGH: "HIGH",
    RiskLevel.EXTREME: "EXTREME",
}

_REC_EMOJI = {
    Recommendation.KEEP: "KEEP",
    Recommendation.SWAP: "SWAP",
    Recommendation.REMOVE: "REMOVE",
}

_SLIP_EMOJI = {
    SlipType.SAFE_STACK: "SAFE STACK",
    SlipType.BALANCED_BUILDER: "BALANCED",
    SlipType.HIGH_RISK_ACCUMULATOR: "HIGH RISK",
    SlipType.LOTTERY_TICKET: "LOTTERY",
}


def format_telegram_message(analysis: SlipAnalysis) -> str:
    """Convert a SlipAnalysis into a clean Telegram message (plain text)."""
    lines: list[str] = []

    # Header
    lines.append("SLIP ANALYSIS")
    lines.append("=" * 24)
    lines.append("")

    # Strategy
    s = _STRATEGY_EMOJI[analysis.strategy]
    lines.append(f"Strategy: {s} - {analysis.strategy.value}")
    lines.append(f"{analysis.strategy_explanation}")
    lines.append("")

    # Per-pick breakdown
    lines.append("-" * 24)
    lines.append("PICK-BY-PICK ANALYSIS")
    lines.append("-" * 24)
    lines.append("")

    for i, pa in enumerate(analysis.pick_analyses, 1):
        p = pa.pick
        r = _RISK_EMOJI[pa.risk_level]
        rec = _REC_EMOJI[pa.recommendation]

        lines.append(f"{i}. {p.home_team} vs {p.away_team}")
        lines.append(f"   {p.selection} @ {p.odds:.2f}")
        lines.append(f"   Risk: {r}")
        lines.append(f"   {pa.insight}")
        lines.append(f"   Verdict: {rec}")
        if pa.alternative_suggestion:
            lines.append(f"   Try instead: {pa.alternative_suggestion}")
        lines.append("")

    # Accumulator
    lines.append("-" * 24)
    lines.append("ACCUMULATOR")
    lines.append("-" * 24)
    sl = _SLIP_EMOJI[analysis.slip_type]
    lines.append(f"Type: {sl}")
    lines.append(f"Combined Odds: {analysis.total_odds:.2f}")
    lines.append(f"Win Probability: ~{analysis.realistic_probability * 100:.1f}%")
    lines.append(f"{analysis.slip_explanation}")
    lines.append("")

    # Final summary
    lines.append("-" * 24)
    lines.append("VERDICT")
    lines.append("-" * 24)
    lines.append("")
    lines.append(analysis.final_summary)
    lines.append("")
    lines.append("Upgrade to VIP for daily optimized picks!")
    lines.append("DM the admin to verify your payment and get access.")

    return "\n".join(lines)
