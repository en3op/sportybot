"""
Betting Research Agent
=====================
Analyzes matches using historical patterns and strategic rules.
Predicts best market outcomes from 20+ SportyBet options.
"""

import logging
import re
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def analyze_match_research(match: dict, research_data: dict = None) -> dict:
    """
    Analyze a single match using the accumulator strategy framework.
    
    Args:
        match: Match data with home, away, league, markets (odds)
        research_data: Optional form/H2H/position data
    
    Returns:
        Analysis dict with tier, confidence, best markets, reasoning
    """
    home = match.get("home", "")
    away = match.get("away", "")
    league = match.get("league", "")
    markets = match.get("markets", {})
    
    analysis = {
        "match": f"{home} vs {away}",
        "league": league,
        "tier": "C",
        "confidence": 50,
        "recommended_markets": [],
        "red_flags": [],
        "boost_factors": [],
        "risk_factors": [],
        "reasoning": "",
    }
    
    # Get 1X2 odds for basic assessment
    odds_1x2 = markets.get("1X2", {})
    home_odds = float(odds_1x2.get("Home", 2.5))
    draw_odds = float(odds_1x2.get("Draw", 3.3))
    away_odds = float(odds_1x2.get("Away", 3.0))
    
    # Determine if home favorite
    is_home_favorite = home_odds < 1.70 and home_odds < away_odds
    is_away_favorite = away_odds < 1.70 and away_odds < home_odds
    
    # Get research data if available
    home_form = research_data.get("home_form", "") if research_data else ""
    away_form = research_data.get("away_form", "") if research_data else ""
    home_pos = research_data.get("home_position", 0) if research_data else 0
    away_pos = research_data.get("away_position", 0) if research_data else 0
    
    # Calculate form scores (W=3, D=1, L=0)
    home_form_score = _calc_form_score(home_form)
    away_form_score = _calc_form_score(away_form)
    
    # ==================== RED FLAG CHECKS ====================
    
    # Rule: Never trust big name bankers
    big_clubs = ["Real Madrid", "Barcelona", "Bayern", "Man City", "Man United", 
                 "Liverpool", "Chelsea", "Arsenal", "PSG", "Juventus", "Inter", 
                 "AC Milan", "Dortmund", "Atletico"]
    is_big_club_home = any(club.lower() in home.lower() for club in big_clubs)
    is_big_club_away = any(club.lower() in away.lower() for club in big_clubs)
    
    if is_big_club_home and home_odds < 1.30:
        analysis["risk_factors"].append("Big name banker - form > reputation")
    
    # Rule: Motivation matters
    if home_pos > 0 and away_pos > 0:
        pos_gap = abs(home_pos - away_pos)
        if pos_gap <= 3 and home_odds < 1.40:
            analysis["red_flags"].append("Similar table positions - motivation unclear")
    
    # Rule: Away favorite risk
    if is_away_favorite and away_odds < 1.40:
        analysis["risk_factors"].append("Away favorite - higher variance")
    
    # Rule: Check for potential dead rubber (late season)
    month = datetime.now().month
    if month in [4, 5, 11, 12]:
        analysis["risk_factors"].append("Late season - check motivation carefully")
    
    # Rule: Derby match detection
    derby_pairs = [
        ("manchester", ["united", "city"]),
        ("liverpool", ["everton"]),
        ("madrid", ["real", "atletico"]),
        ("milan", ["inter", "ac"]),
        ("london", ["arsenal", "chelsea", "tottenham", "west ham"]),
    ]
    for city, teams in derby_pairs:
        if city.lower() in home.lower() or city.lower() in away.lower():
            for t1 in teams:
                for t2 in teams:
                    if t1 != t2 and t1 in home.lower() and t2 in away.lower():
                        analysis["red_flags"].append("Derby match - form unreliable")
    
    # ==================== TIER CALCULATION ====================
    
    tier_score = 0
    
    # Home advantage rule (80% should be home favorites)
    if is_home_favorite:
        tier_score += 20
        analysis["boost_factors"].append("Home favorite")
    
    # Quality gap check (odds-based)
    if home_odds < 1.30:
        tier_score += 15
        analysis["boost_factors"].append("Heavy home favorite")
    elif home_odds < 1.50:
        tier_score += 10
    elif home_odds < 1.70:
        tier_score += 5
    
    # Form advantage
    form_diff = home_form_score - away_form_score
    if form_diff >= 6:  # At least 2W difference
        tier_score += 15
        analysis["boost_factors"].append(f"Form advantage: {home_form or '?'} vs {away_form or '?'}")
    elif form_diff >= 3:
        tier_score += 8
    
    # Position gap
    if home_pos > 0 and away_pos > 0:
        pos_diff = away_pos - home_pos  # Positive = home ranked higher
        if pos_diff >= 10:
            tier_score += 15
            analysis["boost_factors"].append(f"Position gap: #{home_pos} vs #{away_pos}")
        elif pos_diff >= 5:
            tier_score += 8
    
    # League reliability adjustment
    tier1_leagues = ["Premier League", "La Liga", "Serie A", "Bundesliga", 
                     "Ligue 1", "Champions League", "Europa League"]
    tier2_leagues = ["Eredivisie", "Primeira Liga", "Championship", "MLS"]
    
    is_tier1 = any(l.lower() in league.lower() for l in tier1_leagues)
    is_tier2 = any(l.lower() in league.lower() for l in tier2_leagues)
    
    if is_tier1:
        tier_score += 5
    elif not is_tier2:
        tier_score -= 5
        analysis["risk_factors"].append("Lower-tier league")
    
    # Apply red flag penalties
    tier_score -= len(analysis["red_flags"]) * 15
    tier_score -= len(analysis["risk_factors"]) * 5
    
    # Determine tier
    if tier_score >= 45:
        analysis["tier"] = "S"
        analysis["confidence"] = min(95, 75 + tier_score - 45)
    elif tier_score >= 35:
        analysis["tier"] = "A"
        analysis["confidence"] = min(85, 65 + tier_score - 35)
    elif tier_score >= 25:
        analysis["tier"] = "B"
        analysis["confidence"] = min(75, 55 + tier_score - 25)
    else:
        analysis["tier"] = "C"
        analysis["confidence"] = max(35, 50 + tier_score)
    
    # ==================== MARKET RECOMMENDATIONS ====================
    
    analysis["recommended_markets"] = _recommend_markets(
        match, analysis, home_form_score, away_form_score, research_data
    )
    
    # Build reasoning
    reasoning_parts = []
    if analysis["boost_factors"]:
        reasoning_parts.append(f"Pro: {', '.join(analysis['boost_factors'][:3])}")
    if analysis["risk_factors"]:
        reasoning_parts.append(f"Risk: {', '.join(analysis['risk_factors'][:2])}")
    if analysis["red_flags"]:
        reasoning_parts.append(f"WARNING: {', '.join(analysis['red_flags'])}")
    
    analysis["reasoning"] = " | ".join(reasoning_parts) if reasoning_parts else "Standard analysis"
    
    return analysis


def _recommend_markets(match: dict, analysis: dict, 
                       home_form_score: float, away_form_score: float,
                       research_data: dict) -> list:
    """Recommend best markets based on analysis."""
    
    markets = match.get("markets", {})
    recommendations = []
    tier = analysis["tier"]
    confidence = analysis["confidence"]
    
    # Get available odds
    odds_1x2 = markets.get("1X2", {})
    home_odds = float(odds_1x2.get("Home", 2.5))
    draw_odds = float(odds_1x2.get("Draw", 3.3))
    away_odds = float(odds_1x2.get("Away", 3.0))
    
    # Calculate implied probabilities
    home_prob = 1 / home_odds if home_odds > 0 else 0.4
    draw_prob = 1 / draw_odds if draw_odds > 0 else 0.25
    away_prob = 1 / away_odds if away_odds > 0 else 0.35
    
    # Check goal markets
    ou_markets = {k: v for k, v in markets.items() if "Over" in k or "Under" in k}
    btts = markets.get("BTTS", {})
    
    # Estimate total goals - use real data if available
    estimated_goals = _estimate_goals_from_odds(ou_markets, home_prob, away_prob)
    
    # Override with real goals data from SofaScore if available
    if research_data:
        home_gpg = research_data.get("home_goals_scored", 0)
        away_gpg = research_data.get("away_goals_scored", 0)
        if home_gpg > 0 and away_gpg > 0:
            estimated_goals = home_gpg + away_gpg
            if "Real xG verified" not in analysis.get("boost_factors", []):
                analysis["boost_factors"].append(f"Real xG: {estimated_goals:.1f}")

    # ==================== TIER S: ULTRA-SAFE ====================
    if tier == "S":
        # Recommend 1X2 Home
        if home_odds > 1.15:
            recommendations.append({
                "market": "1X2",
                "pick": "Home",
                "odds": home_odds,
                "confidence": confidence,
                "reason": "Ultra-safe home favorite"
            })
        
        # Double Chance 1X if very safe
        dc_1x = markets.get("Double Chance", {}).get("1X", 1.15)
        if dc_1x and dc_1x > 1.08:
            recommendations.append({
                "market": "Double Chance",
                "pick": "1X",
                "odds": dc_1x,
                "confidence": min(95, confidence + 5),
                "reason": "Maximum safety - home or draw"
            })
    
    # ==================== TIER A: VERY SAFE ====================
    elif tier == "A":
        if home_odds > 1.25:
            recommendations.append({
                "market": "1X2",
                "pick": "Home",
                "odds": home_odds,
                "confidence": confidence,
                "reason": "Strong home favorite"
            })
        
        # Goals markets for tier A
        if estimated_goals > 2.3:
            ov15 = _find_over_under_markets(markets, 1.5)
            if ov15 and ov15.get("Over", 0) > 1.15:
                recommendations.append({
                    "market": "Over/Under 1.5",
                    "pick": "Over",
                    "odds": ov15["Over"],
                    "confidence": min(90, confidence + 3),
                    "reason": "High-scoring teams"
                })
    
    # ==================== TIER B: SOLID ====================
    elif tier == "B":
        if home_odds > 1.45:
            recommendations.append({
                "market": "1X2",
                "pick": "Home",
                "odds": home_odds,
                "confidence": confidence,
                "reason": "Decent home favorite"
            })
        
        # Check BTTS if form suggests goals
        btts_yes = btts.get("Yes", 1.75)
        if btts_yes and btts_yes > 1.60 and estimated_goals > 2.0:
            recommendations.append({
                "market": "BTTS",
                "pick": "Yes",
                "odds": btts_yes,
                "confidence": confidence - 5,
                "reason": "Both teams likely to score"
            })
    
    # ==================== TIER C: RISKY ====================
    else:
        # For risky matches, look for value in goals markets
        if estimated_goals < 2.0:
            un15 = _find_over_under_markets(markets, 1.5)
            if un15 and un15.get("Under", 0) > 1.40:
                recommendations.append({
                    "market": "Over/Under 1.5",
                    "pick": "Under",
                    "odds": un15["Under"],
                    "confidence": confidence,
                    "reason": "Low-scoring matchup"
                })
        
        # Draw no bet as safer alternative
        dnb = markets.get("Draw No Bet", {})
        home_dnb = dnb.get("Home", 1.35)
        if home_dnb and home_dnb > 1.25:
            recommendations.append({
                "market": "Draw No Bet",
                "pick": "Home",
                "odds": home_dnb,
                "confidence": confidence + 5,
                "reason": "Safer than 1X2 for risky match"
            })
    
    # ==================== SAFE GOALS PROFILE ====================
    # Always check Over 1.5 for safe goals accumulator
    ov15 = _find_over_under_markets(markets, 1.5)
    if ov15 and ov15.get("Over", 0) > 1.12:
        goals_conf = 75 if estimated_goals > 2.5 else 65 if estimated_goals > 2.0 else 55
        if goals_conf >= 65:
            recommendations.append({
                "market": "Over/Under 1.5",
                "pick": "Over",
                "odds": ov15["Over"],
                "confidence": goals_conf,
                "reason": f"Safe goals option (xG: {estimated_goals:.1f})",
                "profile": "safe_goals"
            })
    
    # BTTS for goal-heavy matches
    if btts and estimated_goals > 2.5:
        btts_yes = btts.get("Yes", 1.75)
        if btts_yes and btts_yes > 1.55:
            recommendations.append({
                "market": "BTTS",
                "pick": "Yes",
                "odds": btts_yes,
                "confidence": 70,
                "reason": "High xG suggests both teams score",
                "profile": "safe_goals"
            })
    
    return recommendations


def _calc_form_score(form: str) -> float:
    """Calculate form score from W/D/L string. W=3, D=1, L=0."""
    if not form:
        return 5.0  # Unknown - neutral
    return sum(3 if c == "W" else 1 if c == "D" else 0 for c in form.upper())


def _estimate_goals_from_odds(ou_markets: dict, home_prob: float, away_prob: float) -> float:
    """Estimate total goals from Over/Under odds."""
    if not ou_markets:
        # Fallback: estimate from win probabilities
        return 2.2 + (home_prob + away_prob - 0.8) * 0.5
    
    best_line = 2.5
    best_diff = 999
    
    for key, outcomes in ou_markets.items():
        line = _extract_total_line(key)
        under = float(outcomes.get("Under", 2.0)) if isinstance(outcomes, dict) else 0
        over = float(outcomes.get("Over", 2.0)) if isinstance(outcomes, dict) else 0
        if under > 1.0 and over > 1.0:
            diff = abs(under - over)
            if diff < best_diff:
                best_diff = diff
                best_line = line
    
    return best_line


def _extract_total_line(market: str) -> float:
    """Extract the total line number from Over/Under market string."""
    match = re.search(r'(\d+\.?\d*)', str(market))
    if match:
        return float(match.group(1))
    return 2.5


def _find_over_under_markets(markets: dict, line: float) -> dict:
    """Find Over/Under market for a specific line."""
    for key, outcomes in markets.items():
        if str(line) in str(key):
            return outcomes if isinstance(outcomes, dict) else {}
    return {}


def score_all_matches(matches: list[dict], research_data: dict = None) -> list[dict]:
    """
    Score all matches and return sorted by confidence.
    
    Args:
        matches: List of match dicts with markets
        research_data: Optional dict of {match_key: research}
    
    Returns:
        List of analysis dicts sorted by confidence
    """
    results = []
    
    for match in matches:
        key = f"{match.get('home', '')} vs {match.get('away', '')}"
        research = research_data.get(key, {}) if research_data else {}
        
        analysis = analyze_match_research(match, research)
        results.append(analysis)
    
    # Sort by confidence descending
    results.sort(key=lambda x: x["confidence"], reverse=True)
    
    return results


def get_top_picks_by_profile(matches: list[dict], profile: str = "standard") -> list[dict]:
    """
    Get top picks for a specific accumulator profile.
    
    Args:
        matches: List of analyzed matches
        profile: "standard", "safe_goals", or "high_risk"
    
    Returns:
        List of recommended picks
    """
    picks = []
    
    for match in matches:
        for rec in match.get("recommended_markets", []):
            if profile == "safe_goals":
                if rec.get("profile") == "safe_goals" or rec["market"] in ["Over/Under 1.5", "BTTS"]:
                    picks.append({**rec, "match": match["match"], "league": match["league"]})
            elif profile == "high_risk":
                if rec["odds"] >= 3.0:
                    picks.append({**rec, "match": match["match"], "league": match["league"]})
            else:  # standard
                if rec.get("profile") != "safe_goals":
                    picks.append({**rec, "match": match["match"], "league": match["league"]})
    
    return sorted(picks, key=lambda x: x["confidence"], reverse=True)
