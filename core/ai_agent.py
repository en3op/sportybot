"""
AI Football Research Agent
===========================
Expert football analyst that researches matches using:
  - REAL team form from API-Football (last 5 W/D/L)
  - Actual goals scored/conceded averages
  - League position from standings
  - Head-to-head historical record
  - Home/away specific form
  - Market odds as supplementary signal

Scores each pick on a 0-100 Expert Confidence scale.
Only selects picks with 70+ confidence.
"""

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

MIN_EXPERT_CONFIDENCE = 70


def research_and_score_events(events: list[dict], use_sofascore: bool = True) -> list[dict]:
    """Research each event using the betting strategy framework.

    Uses research_agent for strategic analysis with historical patterns.
    Optionally enriches with real form data from SofaScore via Playwright.
    """
    sorted_events = sorted(events, key=lambda e: e.get("best_score", 0), reverse=True)

    logger.info(f"AI Agent: Analyzing {len(sorted_events)} events with strategy framework")

    # Batch research from SofaScore (top 15 matches for performance ~2 min)
    sofascore_data = {}
    if use_sofascore and len(sorted_events) > 0:
        top_for_research = sorted_events[:15]
        logger.info(f"Fetching SofaScore form data for top {len(top_for_research)} matches...")
        try:
            from sofascore_scraper import research_matches_batch
            raw_data = research_matches_batch(top_for_research)
            # Convert to research_agent format
            for match_key, data in raw_data.items():
                sofascore_data[match_key] = {
                    'home_form': data.get('home', {}).get('form', ''),
                    'away_form': data.get('away', {}).get('form', ''),
                    'home_position': data.get('home', {}).get('league_position', 0),
                    'away_position': data.get('away', {}).get('league_position', 0),
                    'home_goals_scored': data.get('home', {}).get('goals_scored', 0),
                    'away_goals_scored': data.get('away', {}).get('goals_scored', 0),
                    'home_goals_conceded': data.get('home', {}).get('goals_conceded', 0),
                    'away_goals_conceded': data.get('away', {}).get('goals_conceded', 0),
                }
            logger.info(f"SofaScore data fetched for {len(sofascore_data)} matches")
        except Exception as e:
            logger.warning(f"SofaScore batch research failed: {e}")

    scored = []

    for event in sorted_events:
        from core.research_agent import analyze_match_research

        # Get SofaScore data for this match if available
        home = event.get("home", "")
        away = event.get("away", "")
        match_key = f"{home} vs {away}"
        match_research = sofascore_data.get(match_key)

        analysis = analyze_match_research(event, match_research)

        result = _apply_research_analysis(event, analysis)
        if result:
            scored.append(result)

    logger.info(f"AI Agent: {len(scored)}/{len(events)} events passed expert review")
    return scored


def _apply_research_analysis(event: dict, analysis: dict) -> Optional[dict]:
    """Apply research_agent analysis to event scoring."""

    recommendations = analysis.get("recommended_markets", [])

    # Always set expert_analysis from research_agent (tier, red_flags, etc.)
    expert_analysis = {
        "tier": analysis.get("tier", "C"),
        "red_flags": analysis.get("red_flags", []),
        "boost_factors": analysis.get("boost_factors", []),
        "reasoning": analysis.get("reasoning", ""),
    }

    if not recommendations:
        # Fall back to odds-only but preserve expert_analysis
        result = _score_with_odds_only(event)
        if result:
            result["expert_analysis"] = expert_analysis
        return result

    scored_picks = []

    for rec in recommendations:
        if rec.get("confidence", 0) >= MIN_EXPERT_CONFIDENCE:
            existing = next(
                (p for p in event.get("scored_picks", [])
                if p.get("market") == rec["market"] and p.get("pick") == rec["pick"]),
                None
            )

            if existing:
                existing["expert_confidence"] = rec["confidence"]
                existing["expert_reasoning"] = rec.get("reason", "")
                scored_picks.append(existing)
            else:
                scored_picks.append({
                    "market": rec["market"],
                    "pick": rec["pick"],
                    "odds": rec["odds"],
                    "tier": analysis.get("tier", "C"),
                    "consistency_score": rec["confidence"],
                    "expert_confidence": rec["confidence"],
                    "expert_reasoning": rec.get("reason", ""),
                })

    if not scored_picks:
        # Fall back to odds-only but preserve expert_analysis
        result = _score_with_odds_only(event)
        if result:
            result["expert_analysis"] = expert_analysis
        return result

    scored_picks.sort(key=lambda p: p["expert_confidence"], reverse=True)
    event["scored_picks"] = scored_picks[:3]
    event["best_score"] = scored_picks[0]["expert_confidence"]
    event["expert_analysis"] = expert_analysis
    event["research_source"] = "strategy_framework"

    return event


def _score_with_web_data(event: dict, web_data: dict) -> Optional[dict]:
    """Score event using web search research data."""
    home_form = web_data.get("home_form", "")
    away_form = web_data.get("away_form", "")
    home_gpg = web_data.get("goals_scored", 1.3)
    away_gpg = web_data.get("goals_scored", 1.2)
    home_ga = web_data.get("goals_conceded", 1.1)
    away_ga = web_data.get("goals_conceded", 1.2)
    home_pos = web_data.get("position", 0)
    away_pos = web_data.get("position", 0)
    h2h_home = web_data.get("h2h_home_wins", 0)
    h2h_draws = web_data.get("h2h_draws", 0)
    h2h_away = web_data.get("h2h_away_wins", 0)
    h2h_total = web_data.get("h2h_matches", 0)
    reliability = event.get("reliability", "low")

    factors = {
        "home_form": home_form,
        "away_form": away_form,
        "home_goals_scored": home_gpg,
        "away_goals_scored": away_gpg,
        "home_goals_conceded": home_ga,
        "away_goals_conceded": away_ga,
        "home_position": home_pos,
        "away_position": away_pos,
        "h2h_home_wins": h2h_home,
        "h2h_draws": h2h_draws,
        "h2h_away_wins": h2h_away,
        "h2h_matches": h2h_total,
        "expected_goals": (home_gpg + away_gpg),
        "has_live_data": True,
    }

    picks = event.get("scored_picks", [])
    enriched = []

    for pick in picks:
        result = _score_single_pick(pick, factors, event.get("home", ""), event.get("away", ""), event.get("league", ""), reliability)
        if result["expert_confidence"] >= MIN_EXPERT_CONFIDENCE:
            pick["expert_confidence"] = result["expert_confidence"]
            pick["expert_reasoning"] = result["expert_reasoning"]
            pick["expert_factors"] = result["factors"]
            enriched.append(pick)

    if not enriched:
        return None

    enriched.sort(key=lambda p: p["expert_confidence"], reverse=True)
    event["scored_picks"] = enriched[:3]
    event["best_score"] = enriched[0]["expert_confidence"]
    event["expert_analysis"] = factors
    event["research_source"] = "web_search"

    return event


def _score_with_live_data(event: dict, live_data: dict) -> Optional[dict]:
    """Score event using REAL team data from API-Football."""
    home_data = live_data.get("home", {})
    away_data = live_data.get("away", {})
    h2h = live_data.get("h2h", {})
    league = event.get("league", "")
    reliability = event.get("reliability", "low")

    # Build real factors
    factors = {
        "home_form": home_data.get("form", ""),
        "away_form": away_data.get("form", ""),
        "home_goals_scored": home_data.get("goals_scored_avg", 0),
        "home_goals_conceded": home_data.get("goals_conceded_avg", 0),
        "away_goals_scored": away_data.get("goals_scored_avg", 0),
        "away_goals_conceded": away_data.get("goals_conceded_avg", 0),
        "home_position": home_data.get("league_position", 0),
        "away_position": away_data.get("league_position", 0),
        "home_wins": home_data.get("wins", 0),
        "home_draws": home_data.get("draws", 0),
        "home_losses": home_data.get("losses", 0),
        "away_wins": away_data.get("wins", 0),
        "away_draws": away_data.get("draws", 0),
        "away_losses": away_data.get("losses", 0),
        "home_home_form": home_data.get("home_form", ""),
        "away_away_form": away_data.get("away_form", ""),
        "h2h_matches": h2h.get("matches", 0),
        "h2h_home_wins": h2h.get("home_wins", 0),
        "h2h_draws": h2h.get("draws", 0),
        "h2h_away_wins": h2h.get("away_wins", 0),
        "expected_goals": (home_data.get("goals_scored_avg", 1.2) + away_data.get("goals_scored_avg", 1.0)),
        "has_live_data": True,
    }

    picks = event.get("scored_picks", [])
    enriched = []

    for pick in picks:
        result = _score_single_pick(pick, factors, event.get("home", ""), event.get("away", ""), league, reliability)
        if result["expert_confidence"] >= MIN_EXPERT_CONFIDENCE:
            pick["expert_confidence"] = result["expert_confidence"]
            pick["expert_reasoning"] = result["expert_reasoning"]
            pick["expert_factors"] = result["factors"]
            enriched.append(pick)

    if not enriched:
        return None

    enriched.sort(key=lambda p: p["expert_confidence"], reverse=True)
    event["scored_picks"] = enriched[:3]
    event["best_score"] = enriched[0]["expert_confidence"]
    event["expert_analysis"] = factors
    event["research_source"] = home_data.get("source", "api-football")

    return event


def _score_with_odds_only(event: dict) -> Optional[dict]:
    """Fallback: score using only market odds (no live data)."""
    markets = event.get("markets", {})
    odds_1x2 = markets.get("1X2", {})
    reliability = event.get("reliability", "low")
    league = event.get("league", "")

    home_odds = odds_1x2.get("Home", 3.0)
    away_odds = odds_1x2.get("Away", 3.0)

    # Estimate xG from O/U markets
    ou_markets = {k: v for k, v in markets.items() if "Over" in k or "Under" in k}
    xg = _estimate_xg_from_odds(ou_markets)

    factors = {
        "home_form": "",
        "away_form": "",
        "home_goals_scored": 0,
        "home_goals_conceded": 0,
        "away_goals_scored": 0,
        "away_goals_conceded": 0,
        "home_position": 0,
        "away_position": 0,
        "home_odds": home_odds,
        "away_odds": away_odds,
        "expected_goals": xg,
        "has_live_data": False,
    }

    picks = event.get("scored_picks", [])
    enriched = []

    for pick in picks:
        # Give a base boost from consistency score, add small odds-based adjustment
        confidence = pick.get("consistency_score", 50)
        market = pick.get("market", "")
        selection = pick.get("pick", "")
        odds = pick.get("odds", 2.0)
        boost_factors = []

        if "Over" in market or "Under" in market:
            line = _extract_total_line(market)
            is_under = "Under" in selection
            if is_under and xg < line - 0.5:
                confidence += 5
                boost_factors.append(f"xG ({xg:.1f}) below line ({line})")
            elif not is_under and xg > line + 0.5:
                confidence += 5
                boost_factors.append(f"xG ({xg:.1f}) above line ({line})")

        if reliability == "high":
            confidence += 3
            boost_factors.append("Tier-1 league")

        confidence = min(100, round(confidence, 1))

        if confidence >= MIN_EXPERT_CONFIDENCE:
            pick["expert_confidence"] = confidence
            pick["expert_reasoning"] = " | ".join(boost_factors) if boost_factors else "Odds-based analysis"
            pick["expert_factors"] = {"boost_factors": boost_factors, "risk_factors": []}
            enriched.append(pick)

    if not enriched:
        return None

    enriched.sort(key=lambda p: p["expert_confidence"], reverse=True)
    event["scored_picks"] = enriched[:3]
    event["best_score"] = enriched[0]["expert_confidence"]
    event["expert_analysis"] = factors
    event["research_source"] = "odds-only"

    return event


def _score_single_pick(pick: dict, factors: dict, home: str, away: str, league: str, reliability: str) -> dict:
    """Score a single pick using REAL football data."""
    market = pick.get("market", "")
    selection = pick.get("pick", "")
    odds = pick.get("odds", 2.0)
    consistency = pick.get("consistency_score", 50)

    confidence = consistency
    boost_factors = []
    risk_factors = []

    # === REAL FORM ANALYSIS ===
    home_form = factors.get("home_form", "")
    away_form = factors.get("away_form", "")
    home_gpg = factors.get("home_goals_scored", 0)
    home_ga = factors.get("home_goals_conceded", 0)
    away_gpg = factors.get("away_goals_scored", 0)
    away_ga = factors.get("away_goals_conceded", 0)
    home_pos = factors.get("home_position", 0)
    away_pos = factors.get("away_position", 0)
    h2h_total = factors.get("h2h_matches", 0)

    # Form scoring
    home_form_score = _calc_form_score(home_form)
    away_form_score = _calc_form_score(away_form)

    # Position differential
    pos_diff = 0
    if home_pos > 0 and away_pos > 0:
        pos_diff = away_pos - home_pos  # Positive = home ranked better

    # === 1X2 MARKET ===
    if "1X2" in market or "Home" in selection or "Away" in selection:
        is_home = "Home" in selection
        if is_home:
            if home_form_score >= 12:
                confidence += 6
                boost_factors.append(f"Home form: {home_form}")
            elif home_form_score >= 8:
                confidence += 3
                boost_factors.append(f"Decent home form: {home_form}")
            if away_form_score < 5:
                confidence += 5
                boost_factors.append(f"Away struggling: {away_form}")
            if pos_diff > 5:
                confidence += 4
                boost_factors.append(f"Position gap: {home_pos}v{away_pos}")
            if home_gpg > 1.5:
                confidence += 2
                boost_factors.append(f"Home scores {home_gpg}/game")
            if h2h_total >= 3:
                h2h_hw = factors.get("h2h_home_wins", 0)
                if h2h_hw > h2h_total * 0.5:
                    confidence += 3
                    boost_factors.append(f"H2H favors home ({h2h_hw}W/{h2h_total})")
        else:
            if away_form_score >= 12:
                confidence += 6
                boost_factors.append(f"Away form: {away_form}")
            if home_form_score < 5:
                confidence += 4
                boost_factors.append(f"Home struggling: {home_form}")
            if away_ga < 1.0:
                confidence += 3
                boost_factors.append(f"Away defense solid ({away_ga}/game)")
            confidence -= 3
            risk_factors.append("Away pick riskier")

    # === OVER/UNDER ===
    elif "Over" in market or "Under" in market:
        is_under = "Under" in selection
        line = _extract_total_line(market)
        xg = factors.get("expected_goals", 2.5)

        if is_under:
            if home_gpg < 1.2 and away_gpg < 1.2:
                confidence += 7
                boost_factors.append(f"Low scorers: {home_gpg}+{away_gpg}/game")
            if home_ga < 1.0 or away_ga < 1.0:
                confidence += 4
                boost_factors.append("Strong defense present")
            if xg < line - 0.5:
                confidence += 5
                boost_factors.append(f"xG ({xg:.1f}) well below {line}")
        else:
            if home_gpg > 1.8 or away_gpg > 1.5:
                confidence += 6
                boost_factors.append(f"High scorers: {home_gpg}+{away_gpg}/game")
            if home_ga > 1.5 and away_ga > 1.5:
                confidence += 4
                boost_factors.append("Both defenses leaky")
            if xg > line + 0.5:
                confidence += 5
                boost_factors.append(f"xG ({xg:.1f}) well above {line}")

    # === BTTS ===
    elif "BTTS" in market or "Both" in selection:
        is_yes = "Yes" in selection
        if is_yes:
            if home_gpg > 1.2 and away_gpg > 1.0:
                confidence += 5
                boost_factors.append("Both teams score regularly")
        else:
            if home_ga < 0.8 or away_ga < 0.8:
                confidence += 5
                boost_factors.append("At least one solid defense")

    # === HANDICAP ===
    elif "Handicap" in market or "hcp" in market.lower():
        if pos_diff > 8:
            confidence += 3
            boost_factors.append(f"Big position gap supports handicap")
        else:
            confidence -= 3
            risk_factors.append("Handicap variance")

    # === RELIABILITY ===
    if reliability == "high":
        confidence += 3
        boost_factors.append("Tier-1 league")
    elif reliability == "unreliable":
        confidence -= 8
        risk_factors.append("Unreliable league")

    # === LIVE DATA BONUS ===
    if factors.get("has_live_data"):
        confidence += 2
        if not boost_factors:
            boost_factors.append("Real stats verified")

    confidence = max(0, min(100, round(confidence, 1)))

    reasoning = []
    if boost_factors:
        reasoning.append(f"Pro: {', '.join(boost_factors[:3])}")
    if risk_factors:
        reasoning.append(f"Risk: {', '.join(risk_factors[:2])}")
    if not reasoning:
        reasoning.append("Standard analysis")

    return {
        "expert_confidence": confidence,
        "expert_reasoning": " | ".join(reasoning),
        "factors": {"boost_factors": boost_factors, "risk_factors": risk_factors},
    }


def _calc_form_score(form: str) -> float:
    """Calculate form score from W/D/L string. W=3, D=1, L=0."""
    if not form:
        return 5.0  # Unknown
    return sum(3 if c == "W" else 1 if c == "D" else 0 for c in form)


def _estimate_xg_from_odds(ou_markets: dict) -> float:
    """Estimate expected goals from Over/Under odds."""
    if not ou_markets:
        return 2.5

    best_line = 2.5
    best_diff = 999

    for key, outcomes in ou_markets.items():
        line = _extract_total_line(key)
        under = outcomes.get("Under", 0)
        over = outcomes.get("Over", 0)
        if under > 1.0 and over > 1.0:
            diff = abs(under - over)
            if diff < best_diff:
                best_diff = diff
                best_line = line

    return best_line


def _extract_total_line(market: str) -> float:
    """Extract the total line number from Over/Under market string."""
    match = re.search(r'total[=:]?\s*(\d+\.?\d*)', market)
    if match:
        return float(match.group(1))
    match = re.search(r'(\d+\.?\d*)', market)
    if match:
        return float(match.group(1))
    return 2.5
