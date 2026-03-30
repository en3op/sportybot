"""
Telegram Message Formatter — Enhanced structured output for 3-tier slips.
Respects Telegram's 4000 character limit.
"""

from .config import MAX_TELEGRAM_CHARS
from .rebuild_engine import ConstructedSlip
from .slip_parser import Pick


def format_telegram_message(
    picks: list[Pick],
    slips: list[ConstructedSlip],
    skipped_matches: list[str],
) -> str:
    """Construct the final Telegram message from all analysis layers."""
    sections = []

    # Header
    sections.append(_format_header(len(picks), len(slips), skipped_matches))

    # Each slip
    for slip in slips:
        sections.append(_format_slip(slip))

    # Footer
    sections.append(_format_footer())

    message = "\n".join(sections)

    # Trim if over limit
    if len(message) > MAX_TELEGRAM_CHARS:
        message = _trim_message(message, slips)

    return message


def format_event_slips_message(
    match_plays: dict[str, list[dict]],
    slips: list[ConstructedSlip],
) -> str:
    """Format message from SportyBet live-data slips.

    Args:
        match_plays: {match_name: [plays]} — used to show matched game count
        slips: List of ConstructedSlip objects
    """
    sections = []

    # Header
    matched = len(match_plays)
    sections.append(f"\U0001f3af SLIP OPTIMIZER — LIVE ODDS")
    sections.append(f"{'=' * 30}")
    sections.append(f"Matched: {matched} game(s) from your slip")
    sections.append(f"Generated: {len(slips)} optimized slip variations")
    sections.append(f"Source: SportyBet live market data")
    sections.append("")

    # Each slip
    for slip in slips:
        sections.append(_format_event_slip(slip))

    # Footer
    sections.append(_format_footer())

    message = "\n".join(sections)

    if len(message) > MAX_TELEGRAM_CHARS:
        message = _trim_message(message, slips)

    return message


def _format_header(total_matches: int, slip_count: int, skipped: list[str]) -> str:
    lines = [
        f"\U0001f3af FOOTBALL SLIP OPTIMIZER",
        f"{'=' * 30}",
        f"Received: {total_matches} matches",
        f"Generated: {slip_count} optimized slip variations",
    ]
    if skipped:
        lines.append(f"\u26a0\ufe0f Skipped {len(skipped)} match(es): {', '.join(skipped[:3])}")
    lines.append("")
    return "\n".join(lines)


def _format_slip(slip: ConstructedSlip) -> str:
    """Format a single slip tier with full breakdown."""
    risk_stars = "\u2b50" * slip.risk_stars

    lines = [
        f"{slip.emoji} {slip.name} SLIP",
        f"{'-' * 24}",
        f"Total Odds: {slip.total_odds:.2f}x",
        f"Est. Win Probability: {slip.win_probability:.1f}%",
        f"Risk: {risk_stars}",
        f"Stake: {slip.bankroll_pct} of bankroll",
        f"",
        f"--- Match Breakdown ---",
    ]

    for i, p in enumerate(slip.picks, 1):
        # Score class emoji
        if p.consistency_score >= 80:
            sc_emoji = "\U0001f7e2"
        elif p.consistency_score >= 70:
            sc_emoji = "\U0001f7e1"
        elif p.consistency_score >= 60:
            sc_emoji = "\U0001f7e0"
        else:
            sc_emoji = "\U0001f534"

        lines.append(
            f"{i}. {p.match_name}\n"
            f"   Market: {p.bet_label} @ {p.odds:.2f}\n"
            f"   {sc_emoji} Score: {p.consistency_score}/100 | Base: {p.base_prob:.0f}%"
        )

        if p.penalties:
            lines.append(f"   \u26a0\ufe0f {', '.join(p.penalties[:2])}")
        if p.bonuses:
            lines.append(f"   \u2705 {', '.join(p.bonuses[:1])}")

        # Reason (truncated)
        reason = p.reason
        if len(reason) > 150:
            reason = reason[:147] + "..."
        lines.append(f"   {reason}")
        lines.append("")

    # Summary
    lines.append(f"\U0001f4ca Slip Summary:")
    lines.append(f"  Combined Odds: {slip.total_odds:.2f}x")
    lines.append(f"  Win Probability: {slip.win_probability:.1f}%")
    lines.append(f"  Picks: {len(slip.picks)} | Philosophy: {slip.philosophy}")
    lines.append(f"  Key Risk: {slip.key_risk}")
    lines.append(f"  \U0001f4a1 Pro Tip: {slip.pro_tip}")

    return "\n".join(lines) + "\n\n"


def _format_footer() -> str:
    return (
        f"{'=' * 30}\n"
        f"\U0001f4a1 BANKROLL GUIDANCE:\n"
        f"SAFE: 3-5% | MODERATE: 2-3% | HIGH: 1-2%\n"
        f"Never stake more than 5% total across all slips."
    )


def _format_event_slip(slip: ConstructedSlip) -> str:
    """Format a single slip tier built from live event data."""
    risk_stars = "\u2b50" * slip.risk_stars

    lines = [
        f"{slip.emoji} {slip.name} SLIP",
        f"{'-' * 24}",
        f"Total Odds: {slip.total_odds:.2f}x",
        f"Est. Win Probability: {slip.win_probability:.1f}%",
        f"Risk: {risk_stars}",
        f"Stake: {slip.bankroll_pct} of bankroll",
        "",
    ]

    for i, p in enumerate(slip.picks, 1):
        # Score class emoji
        if p.consistency_score >= 70:
            sc_emoji = "\U0001f7e2"
        elif p.consistency_score >= 55:
            sc_emoji = "\U0001f7e1"
        elif p.consistency_score >= 40:
            sc_emoji = "\U0001f7e0"
        else:
            sc_emoji = "\U0001f534"

        lines.append(
            f"{i}. {p.match_name}\n"
            f"   {p.bet_label} @ {p.odds:.2f}\n"
            f"   {sc_emoji} Implied: {p.base_prob:.0f}% | Odds: {p.odds:.2f}"
        )

        if p.reason:
            reason = p.reason
            if len(reason) > 120:
                reason = reason[:117] + "..."
            lines.append(f"   {reason}")
        lines.append("")

    # Summary
    lines.append(f"\U0001f4ca Slip Summary:")
    lines.append(f"  Combined Odds: {slip.total_odds:.2f}x")
    lines.append(f"  Win Probability: {slip.win_probability:.1f}%")
    lines.append(f"  Picks: {len(slip.picks)} | Philosophy: {slip.philosophy}")
    lines.append(f"  Key Risk: {slip.key_risk}")
    lines.append(f"  \U0001f4a1 Pro Tip: {slip.pro_tip}")

    return "\n".join(lines) + "\n\n"


def _trim_message(message: str, slips: list[ConstructedSlip]) -> str:
    """Trim message to fit Telegram limit, preserving key info."""
    if len(message) <= MAX_TELEGRAM_CHARS:
        return message

    # Build compact version
    lines = message.split("\n")
    result = []
    total = 0

    for line in lines:
        if total + len(line) + 1 > MAX_TELEGRAM_CHARS - 100:
            result.append("\n[... see full analysis above]")
            break
        result.append(line)
        total += len(line) + 1

    return "\n".join(result)
