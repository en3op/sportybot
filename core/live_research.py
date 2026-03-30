"""
Live Football Research Module
=============================
Uses web search to get team form, recent results, H2H for each match.
"""

import logging
import time
import re
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def research_match_web(match: dict) -> dict:
    """Research a single match using web search.
    
    Returns dict with form data, H2H, goals info.
    """
    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "")
    
    result = {
        "home_form": "",
        "away_form": "",
        "home_goals_scored": 0,
        "away_goals_scored": 0,
        "home_goals_conceded": 0,
        "away_goals_conceded": 0,
        "home_position": 0,
        "away_position": 0,
        "h2h_home_wins": 0,
        "h2h_draws": 0,
        "h2h_away_wins": 0,
        "h2h_matches": 0,
        "source": "web_search",
    }
    
    try:
        from core.web_research import search_team_form, search_h2h
        home_data = search_team_form(home, league)
        away_data = search_team_form(away, league)
        h2h_data = search_h2h(home, away)
        
        if home_data:
            result.update({
                "home_form": home_data.get("form", ""),
                "home_goals_scored": home_data.get("goals_scored", 1.3),
                "home_goals_conceded": home_data.get("goals_conceded", 1.1),
                "home_position": home_data.get("position", 0),
            })
        
        if away_data:
            result.update({
                "away_form": away_data.get("form", ""),
                "away_goals_scored": away_data.get("goals_scored", 1.2),
                "away_goals_conceded": away_data.get("goals_conceded", 1.2),
                "away_position": away_data.get("position", 0),
            })
        
        if h2h_data:
            result.update({
                "h2h_home_wins": h2h_data.get("home_wins", 0),
                "h2h_draws": h2h_data.get("draws", 0),
                "h2h_away_wins": h2h_data.get("away_wins", 0),
                "h2h_matches": h2h_data.get("total", 0),
            })
            
    except Exception as e:
        logger.debug(f"Web research failed for {home} vs {away}: {e}")
    
    return result


def research_all_matches_web(matches: list[dict]) -> dict:
    """Research all matches using web search.
    
    Returns dict: {match_key: research_data}
    """
    results = {}
    
    for i, match in enumerate(matches):
        key = f"{match.get('home', '')} vs {match.get('away', '')}"
        
        if i > 0:
            time.sleep(1.5)  # Rate limit
        
        results[key] = research_match_web(match)
        
        if (i + 1) % 10 == 0:
            logger.info(f"  Researched {i + 1}/{len(matches)} matches")
    
    logger.info(f"  Web research complete: {len(results)} matches")
    return results
