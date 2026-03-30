"""
Main Orchestrator — Runs the enhanced analysis pipeline.
Phase 1-4: Parse → Classify → Score → Build Slips → Format
"""

import time
import logging

from .slip_parser import parse_slip, validate_picks, extract_match_names
from .consistency_engine import score_all_picks
from .rebuild_engine import build_three_slips, build_three_slips_from_events
from .formatter import format_telegram_message, format_event_slips_message

logger = logging.getLogger(__name__)


def analyze_slip(raw_input: str) -> str:
    """
    Fallback pipeline (no live data):
    1. Parse input into picks
    2. Score each pick with consistency model
    3. Build SAFE/MODERATE/HIGH slips
    4. Format structured output
    """
    start = time.time()

    picks = parse_slip(raw_input)
    is_valid, error = validate_picks(picks)
    if not is_valid:
        return f"\u274c {error}"

    scores = score_all_picks(picks)
    slips = build_three_slips(scores)

    if not slips:
        return (
            "\u26a0\ufe0f Could not construct viable slips from your picks.\n\n"
            f"Your {len(picks)} pick(s) could not be organized into slips.\n"
            "Try sending a clearer screenshot or pasting picks as text."
        )

    message = format_telegram_message(picks, slips, [])

    elapsed = time.time() - start
    logger.info(f"Fallback analysis completed in {elapsed:.3f}s ({len(picks)} picks, {len(slips)} slips)")

    return message


def analyze_slip_with_events(match_plays: dict[str, list[dict]]) -> str:
    """
    Live-data pipeline: build 3 slips from per-match SportyBet market data.

    Args:
        match_plays: {match_display_name: [list of scored plays from analyze_all_markets_full]}
                     Each play has: market, pick, pick_short, odds, implied, tier, score

    Returns:
        Formatted Telegram message string.
    """
    start = time.time()

    if not match_plays:
        return (
            "\u274c Could not match any of your games to live SportyBet events.\n\n"
            "Try sending a clearer screenshot with visible team names."
        )

    slips = build_three_slips_from_events(match_plays)

    if not slips:
        return (
            "\u26a0\ufe0f Could not construct slips from the matched events.\n\n"
            f"Matched {len(match_plays)} game(s) but couldn't build valid slips."
        )

    message = format_event_slips_message(match_plays, slips)

    elapsed = time.time() - start
    logger.info(f"Live analysis completed in {elapsed:.3f}s ({len(match_plays)} matches, {len(slips)} slips)")

    return message


def get_match_names(raw_input: str) -> list[tuple[str, str]]:
    """Extract team name pairs from raw text for API matching."""
    return extract_match_names(raw_input)
