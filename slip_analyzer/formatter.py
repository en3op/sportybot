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


# =============================================================================
# NEW: Concise format with tier ratings and search context
# =============================================================================

def format_concise_slip_message(
    match_plays: dict,
    slips: list,
    match_tiers: dict = None,
    search_results: dict = None,
    analysis_id: str = None
) -> str:
    """
    Format concise slip output with tier ratings and search context.
    
    Args:
        match_plays: {match_key: [plays]}
        slips: List of ConstructedSlip objects
        match_tiers: {match_key: tier} - S/A/B/C
        search_results: {match_key: search_data}
        analysis_id: ID for /full_<id> command
    
    Returns:
        Concise formatted message string
    """
    lines = []
    
    # Header
    matched_count = len(match_plays)
    search_status = "GLM-5 ✓" if search_results else "Odds-only"
    lines.append("🎯 SLIP ANALYZER")
    lines.append("━" * 28)
    lines.append(f"Matched: {matched_count} games | {search_status}")
    lines.append("")
    
    # Each slip tier
    for slip in slips:
        lines.extend(_format_concise_slip(slip, match_tiers, search_results))
    
    # Expert notes
    if search_results:
        lines.append("📊 EXPERT NOTES:")
        notes = _generate_expert_notes(match_tiers, search_results)
        for note in notes[:3]:
            lines.append(f"• {note}")
        lines.append("")
    
    # Full analysis link
    if analysis_id:
        lines.append(f"📖 /full_{analysis_id} — detailed analysis")
    
    # VIP CTA
    lines.append("")
    lines.append("💎 VIP: ₦500/week → Daily expert picks")
    
    message = "\n".join(lines)
    
    # Ensure within Telegram limit
    if len(message) > MAX_TELEGRAM_CHARS:
        message = message[:MAX_TELEGRAM_CHARS - 50] + "\n[...]"
    
    return message


def _format_concise_slip(slip, match_tiers: dict = None, search_results: dict = None) -> list:
    """Format a single slip in concise format."""
    lines = []
    
    # Slip header
    emoji = slip.emoji if hasattr(slip, 'emoji') else "📊"
    win_pct = f"{slip.win_probability:.0f}%"
    lines.append(f"{emoji} {slip.name} ({slip.total_odds:.2f}x | {win_pct} win)")
    lines.append("─" * 28)
    
    # Picks
    for pick in slip.picks:
        match_name = pick.match_name
        
        # Add tier if available
        tier = match_tiers.get(match_name, "C") if match_tiers else "C"
        tier_display = f"({tier})"
        
        # Get short team names
        if " vs " in match_name:
            parts = match_name.split(" vs ")
            short_name = f"{parts[0][:12]} vs {parts[1][:12]}"
        else:
            short_name = match_name[:25]
        
        # Odds and verdict emoji
        odds = f"@{pick.odds:.2f}"
        
        # Verdict emoji based on confidence
        if pick.base_prob >= 70:
            verdict_emoji = "✅"
        elif pick.base_prob >= 50:
            verdict_emoji = "⚠️"
        else:
            verdict_emoji = "🔴"
        
        # Search context summary
        search_note = ""
        if search_results and match_name in search_results:
            sr = search_results[match_name]
            if sr.get("verdict") == "KEEP":
                search_note = "✓"
            elif sr.get("analysis_summary"):
                summary = sr["analysis_summary"][:30]
                search_note = f"({summary})"
        
        lines.append(f"├─ {short_name} {tier_display}")
        lines.append(f"│  └ {pick.bet_label[:20]} {odds} {verdict_emoji} {search_note}")
    
    # Remove the last ├ and replace with └
    if lines:
        # Find last pick line
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].startswith("├─"):
                lines[i] = lines[i].replace("├─", "└─", 1)
                break
    
    lines.append("")
    return lines


def _generate_expert_notes(match_tiers: dict, search_results: dict) -> list:
    """Generate expert notes based on tiers and search results."""
    notes = []
    
    if not match_tiers and not search_results:
        return ["Analysis based on odds-only data"]
    
    # Tier distribution
    tier_counts = {"S": 0, "A": 0, "B": 0, "C": 0}
    for tier in (match_tiers or {}).values():
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
    
    # Notes based on tier distribution
    if tier_counts.get("S", 0) > 0:
        notes.append("Premium match(es) available — highest confidence")
    if tier_counts.get("C", 0) > tier_counts.get("A", 0):
        notes.append("Multiple risky matches — stake conservatively")
    
    # Notes from search results
    friendly_count = 0
    for match_key, sr in (search_results or {}).items():
        league = sr.get("league", "")
        if "friendly" in league.lower():
            friendly_count += 1
        verdict = sr.get("verdict", "")
        if verdict == "KEEP":
            notes.append(f"{match_key.split(' vs ')[0]} backed by strong form")
    
    if friendly_count > 0:
        notes.append(f"{friendly_count} friendly match(es) — motivation unclear")
    
    return notes if notes else ["All picks analyzed with live search data"]


def format_full_analysis_message(
    match_plays: dict,
    slips: list,
    match_tiers: dict,
    search_results: dict
) -> str:
    """
    Format detailed analysis for /full_<id> command.
    
    Shows complete breakdown including:
    - Full search context
    - All available markets per match
    - Tier classification reasoning
    """
    lines = []
    
    lines.append("📋 FULL ANALYSIS")
    lines.append("=" * 30)
    lines.append("")
    
    # Match details
    for match_key, plays in match_plays.items():
        tier = match_tiers.get(match_key, "C") if match_tiers else "C"
        search = search_results.get(match_key, {}) if search_results else {}
        
        lines.append(f"🏓 {match_key} [{tier}]")
        lines.append("-" * 25)
        
        # Search context
        if search.get("search_context"):
            ctx = search["search_context"][:200]
            lines.append(f"🔍 Search: {ctx}...")
        
        # Form data
        if search.get("form_home"):
            lines.append(f"Form: {search.get('form_home', '?')} vs {search.get('form_away', '?')}")
        
        # Top 5 available plays
        lines.append("Available markets:")
        sorted_plays = sorted(plays, key=lambda p: p.get("score", 0), reverse=True)
        for play in sorted_plays[:5]:
            lines.append(f"  • {play.get('pick', '?')} @ {play.get('odds', 0):.2f} ({play.get('implied', 0):.0f}%)")
        
        lines.append("")
    
    # Slips summary
    lines.append("📊 SLIP BREAKDOWN")
    lines.append("=" * 30)
    
    for slip in slips:
        lines.append(f"\n{slip.name} SLIP:")
        lines.append(f"  Combined: {slip.total_odds:.2f}x")
        lines.append(f"  Win Prob: {slip.win_probability:.1f}%")
        lines.append(f"  Risk: {'⭐' * slip.risk_stars}")
        for pick in slip.picks:
            lines.append(f"  • {pick.match_name}: {pick.bet_label} @ {pick.odds:.2f}")
    
    return "\n".join(lines)
