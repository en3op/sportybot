"""
Data Normalization Engine
=========================
Cleans, deduplicates, standardizes, and tags scraped match data.
"""

import re
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# Known unreliable / low-priority leagues
UNRELIABLE_LEAGUES = {
    "friendly", "friendlies", "test", "exhibition",
    "reserve", "reserves", "youth", "u19", "u20", "u21", "u23",
    "women", "female", "femenina", "frauen",
    "amateur", "pre-season", "training",
}

# Tier 1 leagues (highest reliability)
TIER1_LEAGUES = {
    "premier league", "la liga", "serie a", "bundesliga", "ligue 1",
    "champions league", "europa league", "conference league",
    "copa libertadores", "copa sudamericana",
    "eredivisie", "primeira liga", "scottish premiership",
    "super lig", "saudi pro league", "ligue 1",
}

# Tier 2 leagues (good reliability)
TIER2_LEAGUES = {
    "mls", "a-league", "k league", "j1 league", "j2 league",
    "allsvenskan", "eliteserien", "superliga", "superligaen",
    "bundesliga austria", "pro league", "jupiler pro league",
    "nations league", "laliga", "brazilian serie a", "serie a brazil",
    "liga mx", "primera division", "argentina",
    "premiership", "obos-ligaen",
}

# Market name standardization
MARKET_STANDARDIZATION = {
    "1x2": "1X2",
    "match result": "1X2",
    "match winner": "1X2",
    "home/away": "1X2",
    "gg/ng": "BTTS",
    "both teams to score": "BTTS",
    "both teams to score (yes/no)": "BTTS",
    "goal/no goal": "BTTS",
    "over/under": "Over/Under",
    "double chance": "Double Chance",
    "draw no bet": "Draw No Bet",
    "dnb": "Draw No Bet",
    "handicap": "Handicap",
    "asian handicap": "Handicap",
    "european handicap": "Handicap",
    "correct score": "Correct Score",
    "half time/full time": "HT/FT",
    "first half result": "1H Result",
    "second half result": "2H Result",
}

# Team name aliases for deduplication
TEAM_ALIASES = {
    "manchester united": ["man united", "man utd", "mufc"],
    "manchester city": ["man city", "mcfc"],
    "real madrid": ["r. madrid", "real"],
    "fc barcelona": ["barcelona", "barca"],
    "bayern munich": ["bayern", "fcb"],
    "paris saint-germain": ["psg", "paris sg", "paris st germain"],
    "inter milan": ["inter", "inter milano"],
    "ac milan": ["milan"],
    "atletico madrid": ["atletico", "at. madrid"],
    "tottenham hotspur": ["tottenham", "spurs"],
    "west ham united": ["west ham"],
    "newcastle united": ["newcastle"],
    "wolverhampton wanderers": ["wolves", "wolverhampton"],
    "brighton & hove albion": ["brighton", "brighton hove"],
    "crystal palace": ["cr palace"],
}


def normalize_all(raw_events: list[dict]) -> list[dict]:
    """Full normalization pipeline on raw events.

    Steps:
      1. Clean team names
      2. Deduplicate matches
      3. Standardize market names
      4. Ensure odds are numeric
      5. Tag match reliability
    """
    if not raw_events:
        return []

    # Step 1: Clean team names
    for ev in raw_events:
        ev["home"] = clean_team_name(ev.get("home", ""))
        ev["away"] = clean_team_name(ev.get("away", ""))
        ev["league"] = clean_league_name(ev.get("league", ""))

    # Step 2: Deduplicate
    raw_events = deduplicate_matches(raw_events)

    # Step 3 & 4: Standardize markets + validate odds
    for ev in raw_events:
        ev["markets"] = standardize_markets(ev.get("markets", {}))
        ev["markets"] = validate_odds(ev.get("markets", {}))

    # Step 5: Tag reliability
    for ev in raw_events:
        ev["reliability"] = tag_reliability(ev)
        ev["is_tagged_risky"] = ev["reliability"] in ("low", "unreliable")

    # Sort by reliability then league
    reliability_order = {"high": 0, "medium": 1, "low": 2, "unreliable": 3}
    raw_events.sort(key=lambda e: (reliability_order.get(e.get("reliability", "low"), 9), e.get("league", "")))

    logger.info(f"Normalized {len(raw_events)} events")
    return raw_events


def clean_team_name(name: str) -> str:
    """Clean and normalize team names."""
    if not name:
        return ""

    name = name.strip()

    # Remove common suffixes/prefixes
    name = re.sub(r'\s*\(.*?\)\s*', ' ', name)  # Remove parenthetical
    name = re.sub(r'\s+', ' ', name)  # Normalize whitespace
    name = name.strip()

    # Apply alias resolution
    name_lower = name.lower()
    for canonical, aliases in TEAM_ALIASES.items():
        if name_lower == canonical or name_lower in aliases:
            return canonical.title()

    return name


def clean_league_name(name: str) -> str:
    """Clean league names."""
    if not name:
        return "Unknown"

    name = name.strip()
    # Remove country prefixes in brackets
    name = re.sub(r'^\[.*?\]\s*', '', name)
    # Remove trailing colon and country
    name = re.sub(r'\s*:.*$', '', name)

    return name.strip() or "Unknown"


def deduplicate_matches(events: list[dict]) -> list[dict]:
    """Remove duplicate matches (same teams, same day)."""
    seen = set()
    unique = []

    for ev in events:
        home = ev.get("home", "").lower()
        away = ev.get("away", "").lower()
        key = (home, away)

        if key not in seen:
            seen.add(key)
            unique.append(ev)
        else:
            logger.debug(f"Duplicate removed: {home} vs {away}")

    removed = len(events) - len(unique)
    if removed:
        logger.info(f"Removed {removed} duplicate matches")

    return unique


def standardize_markets(markets: dict) -> dict:
    """Standardize market names to canonical form."""
    standardized = {}

    for key, outcomes in markets.items():
        # Try exact match first
        key_lower = key.lower().strip()

        # Check for prefix matches
        canonical = key  # Default: keep original
        for pattern, standard in MARKET_STANDARDIZATION.items():
            if key_lower.startswith(pattern):
                canonical = standard
                # Preserve any suffix (e.g., "Over/Under(total=2.5)")
                suffix = key[len(pattern):] if len(key) > len(pattern) else ""
                if suffix:
                    # Normalize suffix format
                    suffix = re.sub(r'\(total=(\d+\.?\d*)\)', r'(total=\1)', suffix)
                    canonical = standard + suffix
                break

        # Ensure outcomes values are floats
        clean_outcomes = {}
        for outcome_name, odds_val in outcomes.items():
            try:
                fval = float(odds_val)
                if fval > 0:
                    clean_outcomes[outcome_name.strip()] = fval
            except (ValueError, TypeError):
                continue

        if clean_outcomes:
            standardized[canonical] = clean_outcomes

    return standardized


def validate_odds(markets: dict) -> dict:
    """Ensure all odds are valid numbers within reasonable range."""
    validated = {}

    for market_key, outcomes in markets.items():
        clean = {}
        for name, odds in outcomes.items():
            try:
                fval = float(odds)
                # Odds must be > 1.0 and < 1000 (sanity check)
                if 1.0 < fval < 1000:
                    clean[name] = round(fval, 2)
            except (ValueError, TypeError):
                continue

        if clean:
            validated[market_key] = clean

    return validated


def tag_reliability(event: dict) -> str:
    """Tag match reliability: high / medium / low / unreliable."""
    league = event.get("league", "").lower()
    market_count = event.get("market_count", len(event.get("markets", {})))

    # Check for unreliable leagues
    if any(bad in league for bad in UNRELIABLE_LEAGUES):
        return "unreliable"

    # Tier 1 leagues
    if any(t1 in league for t1 in TIER1_LEAGUES):
        if market_count >= 15:
            return "high"
        return "medium"

    # Tier 2 leagues
    if any(t2 in league for t2 in TIER2_LEAGUES):
        if market_count >= 10:
            return "medium"
        return "low"

    # Unknown leagues
    if market_count >= 20:
        return "medium"
    elif market_count >= 10:
        return "low"

    return "unreliable"


def get_market_count(event: dict) -> int:
    """Count the number of distinct markets available."""
    return len(event.get("markets", {}))


def count_total_markets(events: list[dict]) -> dict:
    """Count total markets across all events for diagnostics."""
    total_markets = sum(len(e.get("markets", {})) for e in events)
    market_types = set()
    for ev in events:
        market_types.update(ev.get("markets", {}).keys())

    return {
        "total_events": len(events),
        "total_markets": total_markets,
        "avg_markets_per_event": round(total_markets / max(len(events), 1), 1),
        "unique_market_types": len(market_types),
        "reliability_breakdown": {
            level: sum(1 for e in events if e.get("reliability") == level)
            for level in ["high", "medium", "low", "unreliable"]
        },
    }
