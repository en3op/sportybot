"""
FotMob Scraper
==============
Fetches match listings from FotMob API.
Combines with SofaScore for team form data.

Endpoints used:
- GET https://www.fotmob.com/api/data/matches?date=YYYYMMDD

Author: SportyBot
"""

import requests
import time
import logging
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FOTMOB_BASE = "https://www.fotmob.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
TIMEOUT = 10
RATE_LIMIT_DELAY = 1


MAJOR_LEAGUES = [
    "Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1",
    "Champions League", "Europa League", "FA Cup", "EFL Cup",
    "Copa del Rey", "DFB-Pokal", "Coppa Italia", "Coupe de France",
    "Eredivisie", "Primeira Liga", "Scottish Premiership",
    "Championship", "League One", "League Two",
    "MLS", "Brasileirão", "Argentinian Primera División",
    "Saudi Pro League", "Turkish Süper Lig", "Belgian Pro League",
    "FIFA World Cup Qualification, UEFA", "FIFA World Cup Qualification",
    "UEFA Nations League", "Africa Cup of Nations Qualification",
    "FIFA Series", "Friendlies", "International Friendlies",
    "Asian Cup Qualification", "Copa America"
]


def fetch_matches_7days(major_leagues_only: bool = True) -> list[dict]:
    """
    Fetch matches for today + next 6 days (7 days total) from FotMob.
    
    Skips cancelled and finished matches.
    
    Returns:
        List of match dicts with:
        - match_id: int
        - league_id: int  
        - league_name: str
        - home_team: str
        - home_id: int
        - away_team: str
        - away_id: int
        - kickoff_utc: str
    """
    matches = []
    today = datetime.now()
    
    for day_offset in range(7):
        date = today + timedelta(days=day_offset)
        date_str = date.strftime("%Y%m%d")
        url = f"{FOTMOB_BASE}/data/matches?date={date_str}"
        
        try:
            logger.info(f"Fetching matches for {date_str}")
            response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
            
            leagues = data.get("leagues", [])
            for league in leagues:
                league_name = league.get("name", "Unknown League")
                league_id = league.get("id", 0)
                
                # Skip non-major leagues if filtering
                if major_leagues_only:
                    if league_name not in MAJOR_LEAGUES:
                        continue
                
                for match in league.get("matches", []):
                    status = match.get("status", {})
                    
                    if status.get("cancelled", False):
                        continue
                    if status.get("finished", False):
                        continue
                    
                    home = match.get("home", {})
                    away = match.get("away", {})
                    
                    match_dict = {
                        "match_id": match.get("id"),
                        "league_id": league_id,
                        "league_name": league_name,
                        "home_team": home.get("name", "Unknown"),
                        "home_id": home.get("id", 0),
                        "away_team": away.get("name", "Unknown"),
                        "away_id": away.get("id", 0),
                        "kickoff_utc": status.get("utcTime", "")
                    }
                    matches.append(match_dict)
                    
            time.sleep(RATE_LIMIT_DELAY)
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error fetching matches for {date_str}: {e}")
            continue
            
    logger.info(f"Found {len(matches)} upcoming matches")
    return matches


def fetch_team_form(team_name: str) -> dict:
    """
    Placeholder - form data not available without SofaScore.
    
    Returns Unknown rating for all teams.
    """
    return {
        "team_name": team_name,
        "form": "",
        "wins": 0,
        "draws": 0,
        "losses": 0,
        "form_rating": "Unknown"
    }


def fetch_match_stats(match_id: int) -> dict:
    """
    Fetch match statistics from FotMob.
    
    Args:
        match_id: FotMob match ID
        
    Returns:
        dict with position and goals per match stats
    """
    url = f"{FOTMOB_BASE}/data/match?id={match_id}"
    
    try:
        response = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
        
        stats = data.get("stats", {}).get("stats", [])
        
        result = {
            "home_position": 0,
            "away_position": 0,
            "home_goals_per_match": 0.0,
            "away_goals_per_match": 0.0,
            "home_conceded_per_match": 0.0,
            "away_conceded_per_match": 0.0
        }
        
        for stat in stats:
            title = stat.get("title", "")
            values = stat.get("stats", [])
            
            if title == "Table position" and len(values) >= 2:
                result["home_position"] = values[0]
                result["away_position"] = values[1]
            elif title == "Goals per match" and len(values) >= 2:
                result["home_goals_per_match"] = values[0]
                result["away_goals_per_match"] = values[1]
            elif title == "Goals conceded per match" and len(values) >= 2:
                result["home_conceded_per_match"] = values[0]
                result["away_conceded_per_match"] = values[1]
        
        return result
        
    except Exception as e:
        logger.error(f"Error fetching match stats for {match_id}: {e}")
        return {
            "home_position": 0,
            "away_position": 0,
            "home_goals_per_match": 0.0,
            "away_goals_per_match": 0.0,
            "home_conceded_per_match": 0.0,
            "away_conceded_per_match": 0.0
        }


def _calculate_position_rating(position, total_teams: int = 20) -> str:
    """
    Calculate form rating from league position.
    
    Lower position = better team.
    
    Ratings:
    - Position 1-4 = "Strong"
    - Position 5-8 = "Good"
    - Position 9-14 = "Mixed"
    - Position 15+ = "Poor"
    """
    if position is None or position == 0:
        return "Unknown"
    
    position = int(position)
    
    if position <= 4:
        return "Strong"
    elif position <= 8:
        return "Good"
    elif position <= 14:
        return "Mixed"
    else:
        return "Poor"


def analyze_fixture(match: dict) -> dict:
    """
    Analyze a fixture using FotMob match stats.
    
    Uses league position and goals per match to determine
    advantage and confidence.
    
    Args:
        match: Match dict from fetch_matches_7days()
        
    Returns:
        dict with analysis results
    """
    home_team = match.get("home_team", "Unknown")
    away_team = match.get("away_team", "Unknown")
    match_id = match.get("match_id")
    
    stats = fetch_match_stats(match_id)
    time.sleep(RATE_LIMIT_DELAY)
    
    home_pos = stats.get("home_position", 0)
    away_pos = stats.get("away_position", 0)
    
    home_rating = _calculate_position_rating(home_pos)
    away_rating = _calculate_position_rating(away_pos)
    
    advantage, confidence = _determine_advantage(home_rating, away_rating)
    
    return {
        "match_id": match_id,
        "fixture": f"{home_team} vs {away_team}",
        "league": match.get("league_name"),
        "kickoff_utc": match.get("kickoff_utc"),
        "home_form": {
            "team_name": home_team,
            "position": home_pos,
            "form_rating": home_rating,
            "goals_per_match": stats.get("home_goals_per_match", 0),
            "conceded_per_match": stats.get("home_conceded_per_match", 0)
        },
        "away_form": {
            "team_name": away_team,
            "position": away_pos,
            "form_rating": away_rating,
            "goals_per_match": stats.get("away_goals_per_match", 0),
            "conceded_per_match": stats.get("away_conceded_per_match", 0)
        },
        "advantage": advantage,
        "confidence": confidence
    }
    
    advantage, confidence = _determine_advantage(
        home_form.get("form_rating", "Unknown"),
        away_form.get("form_rating", "Unknown")
    )
    
    return {
        "match_id": match.get("match_id"),
        "fixture": f"{home_team} vs {away_team}",
        "league": match.get("league_name"),
        "kickoff_utc": match.get("kickoff_utc"),
        "home_form": home_form,
        "away_form": away_form,
        "advantage": advantage,
        "confidence": confidence
    }


def _determine_advantage(home_rating: str, away_rating: str) -> tuple[str, str]:
    """
    Determine advantage and confidence based on form ratings.
    
    Logic:
    - Home "Strong" vs Away "Poor" = Home advantage, High confidence
    - Home "Strong" vs Away "Good" = Home advantage, Medium confidence
    - Home "Good" vs Away "Poor" = Home advantage, Medium confidence
    - Equal ratings = Neutral, Low confidence
    - Reverse for Away advantage
    
    Args:
        home_rating: Form rating for home team
        away_rating: Form rating for away team
        
    Returns:
        Tuple of (advantage, confidence)
    """
    rating_order = {"Strong": 4, "Good": 3, "Mixed": 2, "Poor": 1, "Unknown": 0}
    
    home_score = rating_order.get(home_rating, 0)
    away_score = rating_order.get(away_rating, 0)
    
    if home_score == 0 and away_score == 0:
        return "Neutral", "Low"
    
    if home_score > away_score:
        diff = home_score - away_score
        if diff >= 2:
            return "Home", "High"
        else:
            return "Home", "Medium"
    elif away_score > home_score:
        diff = away_score - home_score
        if diff >= 2:
            return "Away", "High"
        else:
            return "Away", "Medium"
    else:
        return "Neutral", "Low"


def get_best_accumulator(days: int = 7, major_leagues_only: bool = True, max_analyze: int = 50) -> list[dict]:
    """
    Get the best accumulator recommendations.
    
    Filters to only High/Medium confidence fixtures.
    Sorts by confidence (High first).
    Returns top 5 recommendations.
    
    Args:
        days: Number of days to look ahead (default 7)
        major_leagues_only: Only analyze major leagues (default True)
        max_analyze: Maximum matches to analyze (default 50)
        
    Returns:
        List of fixture analysis dicts
    """
    matches = fetch_matches_7days(major_leagues_only=major_leagues_only)
    
    # Limit matches to analyze for performance
    matches = matches[:max_analyze]
    
    analyzed = []
    for match in matches:
        analysis = analyze_fixture(match)
        analyzed.append(analysis)
    
    filtered = [
        a for a in analyzed 
        if a["confidence"] in ("High", "Medium")
    ]
    
    confidence_order = {"High": 2, "Medium": 1, "Low": 0}
    filtered.sort(
        key=lambda x: confidence_order.get(x["confidence"], 0), 
        reverse=True
    )
    
    return filtered[:5]


def populate_pool_from_fotmob(major_leagues_only: bool = True, max_matches: int = 100) -> int:
    """
    Populate prediction_pool.db with matches from FotMob.
    
    Args:
        major_leagues_only: Only include major leagues (default True)
        max_matches: Maximum matches to store (default 100)
        
    Returns:
        Number of matches stored
    """
    import sqlite3
    import os
    
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prediction_pool.db")
    
    matches = fetch_matches_7days(major_leagues_only=major_leagues_only)
    matches = matches[:max_matches]
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    stored = 0
    for match in matches:
        match_id = str(match.get("match_id"))
        
        # Check if already exists
        existing = cursor.execute(
            "SELECT match_id FROM matches WHERE match_id = ?", 
            (match_id,)
        ).fetchone()
        
        if existing:
            continue
        
        # Insert match
        cursor.execute("""
            INSERT INTO matches (match_id, league, match_date, home_team, away_team, status, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id,
            match.get("league_name", "Unknown"),
            match.get("kickoff_utc", ""),
            match.get("home_team"),
            match.get("away_team"),
            "scheduled",
            "fotmob"
        ))
        
        stored += 1
    
    conn.commit()
    conn.close()
    
    logger.info(f"Stored {stored} new matches from FotMob")
    return stored


def populate_predictions_from_fotmob(max_analyze: int = 50) -> int:
    """
    Analyze matches and store predictions in prediction_pool.db.
    
    Args:
        max_analyze: Maximum matches to analyze (default 50)
        
    Returns:
        Number of predictions stored
    """
    import sqlite3
    import os
    
    DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prediction_pool.db")
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get matches without predictions
    matches = cursor.execute("""
        SELECT match_id, home_team, away_team, league, match_date 
        FROM matches 
        WHERE source = 'fotmob'
        ORDER BY match_date
        LIMIT ?
    """, (max_analyze,)).fetchall()
    
    stored = 0
    for match in matches:
        match_id = match["match_id"]
        home_team = match["home_team"]
        away_team = match["away_team"]
        
        # Analyze fixture
        match_dict = {
            "match_id": int(match_id),
            "home_team": home_team,
            "away_team": away_team,
            "league_name": match["league"],
            "kickoff_utc": match["match_date"]
        }
        
        analysis = analyze_fixture(match_dict)
        
        # Determine the pick based on advantage
        if analysis["advantage"] == "Home":
            pick = home_team
            market = "1X2"
        elif analysis["advantage"] == "Away":
            pick = away_team
            market = "1X2"
        else:
            continue  # Skip neutral predictions
        
        # Estimate odds based on position
        home_pos = analysis["home_form"].get("position", 10)
        away_pos = analysis["away_form"].get("position", 10)
        
        odds = _estimate_odds_from_position(home_pos, away_pos, analysis["advantage"])
        
        # Insert prediction
        cursor.execute("""
            INSERT INTO predictions (match_id, market, pick, odds, confidence, risk_tier, reasoning)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            match_id,
            market,
            pick,
            odds,
            80 if analysis["confidence"] == "High" else 60,
            analysis["advantage"].lower(),
            f"Position-based: Home #{home_pos} vs Away #{away_pos}"
        ))
        
        stored += 1
        time.sleep(RATE_LIMIT_DELAY)
    
    conn.commit()
    conn.close()
    
    logger.info(f"Stored {stored} predictions from FotMob analysis")
    return stored


def _estimate_odds_from_position(home_pos, away_pos, advantage: str) -> float:
    """
    Estimate odds based on position differential.
    
    Args:
        home_pos: Home team league position
        away_pos: Away team league position  
        advantage: Which team has advantage
        
    Returns:
        Estimated odds
    """
    if home_pos is None or away_pos is None:
        return 1.85
    
    home_pos = int(home_pos) if home_pos else 10
    away_pos = int(away_pos) if away_pos else 10
    
    pos_diff = abs(home_pos - away_pos)
    
    if advantage == "Home":
        if pos_diff >= 10:
            return 1.25
        elif pos_diff >= 5:
            return 1.45
        else:
            return 1.65
    else:  # Away
        if pos_diff >= 10:
            return 1.85
        elif pos_diff >= 5:
            return 2.10
        else:
            return 2.50


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--populate":
        print("=== Populating prediction pool from FotMob ===")
        
        # Step 1: Populate matches
        print("\n1. Fetching and storing matches...")
        matches_stored = populate_pool_from_fotmob(max_matches=100)
        print(f"   Stored {matches_stored} new matches")
        
        # Step 2: Analyze and store predictions
        print("\n2. Analyzing and storing predictions...")
        preds_stored = populate_predictions_from_fotmob(max_analyze=30)
        print(f"   Stored {preds_stored} predictions")
        
        print("\n=== Done ===")
    
    else:
        print("=== FotMob Scraper Test ===")
        print("\n1. Fetching matches for next 7 days...")
        matches = fetch_matches_7days()
        print(f"   Found {len(matches)} matches")
        
        if matches:
            print("\n2. Analyzing first 3 matches (quick test)...")
            for i, match in enumerate(matches[:3]):
                print(f"\n   Match {i+1}: {match['home_team']} vs {match['away_team']}")
                print(f"   League: {match['league_name']}")
                analysis = analyze_fixture(match)
                print(f"   Home form: {analysis['home_form'].get('form', 'N/A')} ({analysis['home_form'].get('form_rating', 'N/A')})")
                print(f"   Away form: {analysis['away_form'].get('form', 'N/A')} ({analysis['away_form'].get('form_rating', 'N/A')})")
                print(f"   Advantage: {analysis['advantage']}")
                print(f"   Confidence: {analysis['confidence']}")
                if i < 2:
                    print("   ---")
        
        print("\n3. Test complete. Run get_best_accumulator() separately for full analysis.")
