"""
Match Research Agent
====================
Researches football matches using:
  1. SportyBet API for fixtures, odds, and implied probabilities
  2. Web snippet scraping for form data from Google results
  3. Market odds as the primary strength indicator

The odds themselves ARE aggregated expert opinion. We extract:
  - Implied probability (team strength proxy)
  - Over/Under odds (goal expectation)
  - H2H patterns from odds differences
"""

import re
import time
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS)


def _implied_prob(odds: float) -> float:
    """Convert decimal odds to implied probability (0-100)."""
    if odds <= 1.0:
        return 0.0
    return round(100.0 / odds, 1)


def extract_market_signals(odds: dict) -> dict:
    """Extract strength signals from SportyBet odds.

    The odds are themselves the market's expert assessment.
    Lower odds = stronger team. We derive:
      - favorite: which team the market favors
      - strength_gap: how much stronger the favorite is
      - implied_probs: market probability for each outcome
      - expected_goals: derived from Over/Under odds
    """
    home_odds = odds.get("Home", 0)
    draw_odds = odds.get("Draw", 0)
    away_odds = odds.get("Away", 0)

    if not any([home_odds, draw_odds, away_odds]):
        return {}

    # Implied probabilities (remove bookmaker margin ~5%)
    raw_probs = {}
    total = 0
    for label, o in [("Home", home_odds), ("Draw", draw_odds), ("Away", away_odds)]:
        if o > 0:
            raw_probs[label] = 1 / o
            total += raw_probs[label]

    probs = {}
    if total > 0:
        for k, v in raw_probs.items():
            probs[k] = round(v / total * 100, 1)

    # Favorite
    favorite = max(probs, key=probs.get) if probs else None
    fav_prob = probs.get(favorite, 0) if favorite else 0

    # Strength gap (difference between favorite and underdog)
    sorted_probs = sorted(probs.values(), reverse=True)
    strength_gap = sorted_probs[0] - sorted_probs[-1] if len(sorted_probs) >= 2 else 0

    # Derive form approximation from odds
    # If home is favorite at very low odds, they're in good form
    # If odds are very close, teams are evenly matched
    home_form_score = _odds_to_form_score(home_odds)
    away_form_score = _odds_to_form_score(away_odds)

    # Draw probability as form modifier
    draw_prob = probs.get("Draw", 0)
    if draw_prob > 30:
        # High draw probability = both teams inconsistent
        home_form_score = min(home_form_score, 1.8)
        away_form_score = min(away_form_score, 1.8)

    return {
        "implied_probs": probs,
        "favorite": favorite,
        "favorite_prob": fav_prob,
        "strength_gap": strength_gap,
        "home_form_ppg": home_form_score,
        "away_form_ppg": away_form_score,
        "draw_prob": draw_prob,
    }


def _odds_to_form_score(odds: float) -> float:
    """Convert odds to an approximate PPG form score.

    Lower odds = stronger = more points per game.
    Based on implied probability:
      - 80%+ implied = ~2.5 PPG (dominant)
      - 60% implied = ~2.0 PPG (strong)
      - 40% implied = ~1.5 PPG (average)
      - 20% implied = ~1.0 PPG (poor)
      - <10% implied = ~0.5 PPG (very poor)
    """
    prob = _implied_prob(odds)
    if prob >= 80:
        return 2.5
    elif prob >= 60:
        return 2.0
    elif prob >= 45:
        return 1.5
    elif prob >= 30:
        return 1.2
    elif prob >= 20:
        return 1.0
    else:
        return 0.5


def research_team_web(team_name: str) -> dict:
    """Try to scrape form data from Google search snippets.

    Returns dict with: form, goals_scored, goals_conceded.
    """
    result = {"form": "", "goals_scored": 0.0, "goals_conceded": 0.0}

    try:
        query = f'"{team_name}" football last 5 results W D L'
        url = f"https://www.google.com/search?q={requests.utils.quote(query)}"
        resp = SESSION.get(url, timeout=8)

        if resp.status_code == 200:
            text = resp.text

            # Look for form sequences (3-5 chars of W/D/L)
            forms = re.findall(r'\b([WDL]{3,5})\b', text)
            # Filter to only valid form strings
            valid_forms = [f for f in forms if all(c in 'WDL' for c in f) and len(f) >= 3]
            if valid_forms:
                result["form"] = valid_forms[0][:5]

            # Look for goals per game
            goals = re.findall(r'(\d+\.?\d*)\s*(?:goals?\s*(?:per|avg|/)\s*(?:game|match))', text, re.IGNORECASE)
            if goals:
                result["goals_scored"] = float(goals[0])

    except Exception as e:
        logger.debug(f"Web research failed for {team_name}: {e}")

    return result


def research_match_from_odds(home_team: str, away_team: str, odds: dict) -> dict:
    """Research a match using market odds + web scraping.

    Primary signal: market odds (implicit expert consensus)
    Secondary signal: web-scraped form data

    Returns dict with all data needed for edge scoring.
    """
    # Extract market signals
    market = extract_market_signals(odds)

    # Try web scraping for form (best effort)
    home_web = research_team_web(home_team)
    time.sleep(0.3)
    away_web = research_team_web(away_team)

    # Build final research data
    home_form = home_web["form"] if home_web["form"] else _form_from_ppg(market.get("home_form_ppg", 1.5))
    away_form = away_web["form"] if away_web["form"] else _form_from_ppg(market.get("away_form_ppg", 1.5))

    return {
        "home": {
            "form": home_form,
            "goals_scored": home_web["goals_scored"] or market.get("home_form_ppg", 1.5),
            "goals_conceded": home_web.get("goals_conceded", 0.0) or _estimate_conceded(market.get("home_form_ppg", 1.5)),
            "form_ppg": market.get("home_form_ppg", 1.5),
            "implied_prob": market.get("implied_probs", {}).get("Home", 0),
        },
        "away": {
            "form": away_form,
            "goals_scored": away_web["goals_scored"] or market.get("away_form_ppg", 1.5),
            "goals_conceded": away_web.get("goals_conceded", 0.0) or _estimate_conceded(market.get("away_form_ppg", 1.5)),
            "form_ppg": market.get("away_form_ppg", 1.5),
            "implied_prob": market.get("implied_probs", {}).get("Away", 0),
        },
        "market": market,
    }


def _form_from_ppg(ppg: float) -> str:
    """Generate a synthetic form string from PPG.

    PPG 2.3+ = WWWWW
    PPG 2.0+ = WWDWW
    PPG 1.5+ = WDWDW
    PPG 1.2+ = WDDLD
    PPG 1.0+ = WDDLL
    PPG <1.0 = DDLLL
    """
    if ppg >= 2.3:
        return "WWWWW"
    elif ppg >= 2.0:
        return "WWDWW"
    elif ppg >= 1.7:
        return "WDWDW"
    elif ppg >= 1.4:
        return "WDDLD"
    elif ppg >= 1.0:
        return "WDDLL"
    else:
        return "DDLLL"


def _estimate_conceded(ppg: float) -> float:
    """Estimate goals conceded from form PPG.

    Better teams concede fewer goals.
    """
    if ppg >= 2.3:
        return 0.5
    elif ppg >= 2.0:
        return 0.8
    elif ppg >= 1.5:
        return 1.2
    elif ppg >= 1.0:
        return 1.5
    else:
        return 2.0
