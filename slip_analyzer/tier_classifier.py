"""
Tier Classifier
===============
Classify matches as S/A/B/C based on league quality and odds profile.

S: Tier-1 league + heavy favorite (odds < 1.50) + clear form advantage
A: Tier-1 league + moderate favorite (odds 1.50-2.00) OR Tier-2 strong favorite
B: Tier-2 league + moderate odds OR Tier-1 with unclear favorite
C: Friendlies, Tier-3 leagues, or unclear motivation
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# League quality tiers
TIER_1_LEAGUES = [
    "Premier League", "La Liga", "Serie A", "Bundesliga", "Ligue 1",
    "Champions League", "Europa League", "World Cup", "Euros",
    "Copa America", "Africa Cup of Nations"
]

TIER_2_LEAGUES = [
    "Eredivisie", "Liga Portugal", "Primeira Liga", "Championship",
    "MLS", "Copa Libertadores", "Saudi Pro League", "Liga MX",
    "Scottish Premiership", "Belgian Pro League", "Austrian Bundesliga"
]

TIER_3_LEAGUES = [
    "League One", "League Two", "Serie B", "La Liga 2",
    "Ligue 2", "2. Bundesliga", "Primeira Liga 2"
]

# Matches that should always be C (motivation unclear)
UNCLEAR_MOTIVATION_KEYWORDS = [
    "Friendly", "International Friendly", "Int. Friendly",
    "Club Friendly", "Test Match", "Exhibition"
]


def classify_match_tier(
    home: str,
    away: str,
    league: str,
    home_odds: float,
    away_odds: float = None,
    form_home: str = "",
    form_away: str = "",
    position_home: int = 0,
    position_away: int = 0
) -> str:
    """
    Classify match quality as S/A/B/C.
    
    Args:
        home: Home team name
        away: Away team name
        league: League/competition name
        home_odds: Home win odds
        away_odds: Away win odds (optional)
        form_home: Home team form string (e.g., "WWLDW")
        form_away: Away team form string
        position_home: Home team league position
        position_away: Away team league position
    
    Returns:
        Tier: "S", "A", "B", or "C"
    """
    if not league:
        league = ""
    
    league_lower = league.lower()
    
    # Check for friendlies/matches with unclear motivation
    for keyword in UNCLEAR_MOTIVATION_KEYWORDS:
        if keyword.lower() in league_lower:
            logger.info(f"Tier C (friendly): {home} vs {away} - {league}")
            return "C"
    
    # Determine league tier
    is_tier1 = any(t1.lower() in league_lower for t1 in TIER_1_LEAGUES)
    is_tier2 = any(t2.lower() in league_lower for t2 in TIER_2_LEAGUES)
    is_tier3 = any(t3.lower() in league_lower for t3 in TIER_3_LEAGUES)
    
    # Calculate form scores (W=3, D=1, L=0)
    form_score_home = _calc_form_score(form_home)
    form_score_away = _calc_form_score(form_away)
    
    # Calculate position gap (positive = home ranked higher)
    pos_gap = 0
    if position_home > 0 and position_away > 0:
        pos_gap = position_away - position_home
    
    # Classification logic
    
    # TIER S: Heavy favorite in Tier-1 league with strong indicators
    if is_tier1:
        if home_odds < 1.35:
            # Very heavy favorite
            if form_score_home >= 10 or pos_gap >= 8:
                return "S"
            return "A"
        elif home_odds < 1.50:
            # Strong favorite
            if form_score_home >= 8 or pos_gap >= 5:
                return "A"
            return "B"
        elif home_odds < 2.00:
            # Moderate favorite
            if form_score_home >= 10:
                return "A"
            return "B"
        else:
            # No clear favorite
            return "B"
    
    # TIER A: Tier-2 strong favorite or Tier-1 moderate
    if is_tier2:
        if home_odds < 1.50:
            if form_score_home >= 10 or pos_gap >= 6:
                return "A"
            return "B"
        elif home_odds < 2.00:
            return "B"
        else:
            return "C"
    
    # TIER B: Tier-3 with clear favorite or Tier-2 moderate
    if is_tier3:
        if home_odds < 1.60:
            return "B"
        return "C"
    
    # Default to C for unknown leagues
    logger.info(f"Tier C (unknown league): {home} vs {away} - {league}")
    return "C"


def _calc_form_score(form: str) -> int:
    """Calculate form score from W/D/L string."""
    if not form:
        return 0
    score = 0
    for c in form.upper():
        if c == "W":
            score += 3
        elif c == "D":
            score += 1
    return score


def get_tier_emoji(tier: str) -> str:
    """Get emoji for tier display."""
    emojis = {
        "S": "⭐",
        "A": "🟢",
        "B": "🟡",
        "C": "🔴"
    }
    return emojis.get(tier, "⚪")


def get_tier_description(tier: str) -> str:
    """Get description for tier."""
    descriptions = {
        "S": "Premium match - heavy favorite with strong form",
        "A": "Quality match - good value with solid indicators",
        "B": "Standard match - moderate risk/reward",
        "C": "Risky match - unclear motivation or lower tier"
    }
    return descriptions.get(tier, "Unknown tier")


def get_tier_confidence_boost(tier: str) -> int:
    """Get confidence boost for tier."""
    boosts = {
        "S": 15,
        "A": 10,
        "B": 0,
        "C": -10
    }
    return boosts.get(tier, 0)


def is_league_tier1(league: str) -> bool:
    """Check if league is Tier-1."""
    if not league:
        return False
    league_lower = league.lower()
    return any(t1.lower() in league_lower for t1 in TIER_1_LEAGUES)


def is_league_tier2(league: str) -> bool:
    """Check if league is Tier-2."""
    if not league:
        return False
    league_lower = league.lower()
    return any(t2.lower() in league_lower for t2 in TIER_2_LEAGUES)


def is_friendly_match(league: str) -> bool:
    """Check if match is a friendly."""
    if not league:
        return False
    league_lower = league.lower()
    return any(kw.lower() in league_lower for kw in UNCLEAR_MOTIVATION_KEYWORDS)
