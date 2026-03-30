"""
Main Orchestrator — Runs the enhanced analysis pipeline.
Phase 1-4: Parse → Search → Classify → Score → Build Slips → Format
"""

import time
import logging
import uuid
from typing import Callable

from .slip_parser import parse_slip, validate_picks, extract_match_names
from .consistency_engine import score_all_picks
from .rebuild_engine import build_three_slips, build_three_slips_from_events, build_three_slips_target_odds
from .formatter import format_telegram_message, format_event_slips_message, format_concise_slip_message, format_full_analysis_message
from .tier_classifier import classify_match_tier
from .search_analyzer import search_matches_batch

logger = logging.getLogger(__name__)

# In-memory store for full analysis (for /full_<id> command)
_analysis_store = {}


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


def analyze_slip_enhanced(
    match_plays: dict[str, list[dict]],
    match_info: dict = None,
    use_search: bool = True,
    progress_callback: Callable = None
) -> tuple[str, str]:
    """
    Enhanced pipeline with search, tier classification, and target-odds slip building.
    
    Args:
        match_plays: {match_key: [plays]} from SportyBet API
        match_info: Optional {match_key: {home, away, league, home_odds}}
        use_search: Whether to use DuckDuckGo search (default True)
        progress_callback: Optional callback(current, total, match_key) for progress
    
    Returns:
        Tuple of (concise_message, analysis_id)
    """
    start = time.time()
    
    if not match_plays:
        return "\u274c Could not match any games to live events.", None
    
    # Generate analysis ID
    analysis_id = str(uuid.uuid4())[:8]
    
    # Step 1: Search for match context (if enabled)
    search_results = {}
    if use_search:
        matches_to_search = []
        for match_key in match_plays.keys():
            if match_info and match_key in match_info:
                info = match_info[match_key]
                matches_to_search.append({
                    "home": info.get("home", ""),
                    "away": info.get("away", "")
                })
            else:
                # Parse from match_key
                parts = match_key.split(" vs ")
                if len(parts) == 2:
                    matches_to_search.append({"home": parts[0], "away": parts[1]})
        
        if matches_to_search:
            logger.info(f"Searching {len(matches_to_search)} matches...")
            search_results = search_matches_batch(matches_to_search, progress_callback)
    
    # Step 2: Classify tiers for each match
    match_tiers = {}
    for match_key in match_plays.keys():
        plays = match_plays[match_key]
        
        # Get odds from first play
        home_odds = 2.5  # Default
        if plays:
            for p in plays:
                if p.get("market") == "1X2" and "Win (1)" in p.get("pick", ""):
                    home_odds = p.get("odds", 2.5)
                    break
        
        # Get league if available
        league = ""
        if match_info and match_key in match_info:
            league = match_info[match_key].get("league", "")
        
        # Get search data
        search_data = search_results.get(match_key, {})
        form_home = search_data.get("form_home", "")
        form_away = search_data.get("form_away", "")
        pos_home = search_data.get("position_home", 0)
        pos_away = search_data.get("position_away", 0)
        
        # Classify
        tier = classify_match_tier(
            home=match_key.split(" vs ")[0] if " vs " in match_key else "",
            away=match_key.split(" vs ")[1] if " vs " in match_key else "",
            league=league,
            home_odds=home_odds,
            form_home=form_home,
            form_away=form_away,
            position_home=pos_home,
            position_away=pos_away
        )
        match_tiers[match_key] = tier
    
    # Step 3: Build 3 slips with target odds
    slips = build_three_slips_target_odds(match_plays, match_tiers)
    
    if not slips:
        # Fallback to original builder
        slips = build_three_slips_from_events(match_plays)
    
    if not slips:
        # Provide helpful error message
        if len(match_plays) < 2:
            return (
                "\u26a0\ufe0f Only 1 match found.\n\n"
                f"Matched: {list(match_plays.keys())[0] if match_plays else 'None'}\n\n"
                "I need at least 2 matches to build slip combinations.\n"
                "Try sending a clearer photo with more games visible."
            ), None
        return (
            "\u26a0\ufe0f Could not construct valid slips.\n\n"
            f"Matched {len(match_plays)} game(s) but couldn't build combinations.\n"
            "Try sending a clearer screenshot with visible team names."
        ), None
    
    # Step 4: Format concise message
    message = format_concise_slip_message(
        match_plays=match_plays,
        slips=slips,
        match_tiers=match_tiers,
        search_results=search_results,
        analysis_id=analysis_id
    )
    
    # Store full analysis for /full command
    _analysis_store[analysis_id] = {
        "match_plays": match_plays,
        "slips": slips,
        "match_tiers": match_tiers,
        "search_results": search_results,
        "timestamp": time.time()
    }
    
    elapsed = time.time() - start
    logger.info(f"Enhanced analysis completed in {elapsed:.3f}s ({len(match_plays)} matches, {len(slips)} slips)")
    
    return message, analysis_id


def get_full_analysis(analysis_id: str) -> str:
    """
    Get full analysis for /full_<id> command.
    
    Args:
        analysis_id: Analysis ID from previous analysis
    
    Returns:
        Formatted full analysis message
    """
    if analysis_id not in _analysis_store:
        return f"\u274c Analysis not found. ID: {analysis_id}"
    
    data = _analysis_store[analysis_id]
    
    return format_full_analysis_message(
        match_plays=data["match_plays"],
        slips=data["slips"],
        match_tiers=data["match_tiers"],
        search_results=data.get("search_results", {})
    )


def cleanup_old_analyses(max_age_hours: int = 24):
    """Remove old analyses from memory store."""
    current_time = time.time()
    max_age_seconds = max_age_hours * 3600
    
    to_remove = []
    for aid, data in _analysis_store.items():
        if current_time - data.get("timestamp", 0) > max_age_seconds:
            to_remove.append(aid)
    
    for aid in to_remove:
        del _analysis_store[aid]
    
    if to_remove:
        logger.info(f"Cleaned up {len(to_remove)} old analyses")


def get_match_names(raw_input: str) -> list[tuple[str, str]]:
    """Extract team name pairs from raw text for API matching."""
    return extract_match_names(raw_input)
