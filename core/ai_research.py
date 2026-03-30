"""
AI Research Module
================
Uses OpenAI-compatible API (NVIDIA NIM) to research football matches.
"""

import logging
import os

logger = logging.getLogger(__name__)

NVIDIA_API_KEY = "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"

from openai import OpenAI

_client = None


def _get_client():
    global _client
    if _client is None:
        _client = OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
        )
    return _client


def research_team_with_ai(team: str, league: str = "") -> dict:
    """Use AI to get team form and analysis."""
    try:
        client = _get_client()

        prompt = f"""Provide brief football team information for {team} in {league if league else 'recent'} football.

Return ONLY a JSON object with these exact fields (no other text):
{{
  "form": "Last 5 match results as W/D/L (e.g., 'WWDLW') or 'unknown'",
  "goals_scored": average goals scored per match (decimal),
  "goals_conceded": average goals conceded per match (decimal),
  "position": league position number or 0 if unknown,
  "home_strength": "strong" / "average" / "weak" / "unknown",
  "away_strength": "strong" / "average" / "weak" / "unknown"
}}"""

        response = client.chat.completions.create(
            model="z-ai/glm5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )

        import json
        import re

        text = response.choices[0].message.content.strip()

        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "form": data.get("form", ""),
                "goals_scored": float(data.get("goals_scored", 1.3)),
                "goals_conceded": float(data.get("goals_conceded", 1.2)),
                "position": int(data.get("position", 0)),
                "source": "ai_nvidia"
            }

        return {}

    except Exception as e:
        logger.debug(f"AI research failed for {team}: {e}")
        return {}


def research_h2h_with_ai(team1: str, team2: str) -> dict:
    """Use AI to get head-to-head record."""
    try:
        client = _get_client()

        prompt = f"""Provide head-to-head record between {team1} and {team2}.

Return ONLY a JSON object with these exact fields:
{{
  "team1_wins": number,
  "draws": number,
  "team2_wins": number,
  "recent_meetings": ["scoreboard for last 3 matches"],
  "insight": "brief insight on who has edge"
}}"""

        response = client.chat.completions.create(
            model="z-ai/glm5",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=500
        )

        import json
        import re

        text = response.choices[0].message.content.strip()

        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            return {
                "h2h_home_wins": int(data.get("team1_wins", 0)),
                "h2h_away_wins": int(data.get("team2_wins", 0)),
                "h2h_draws": int(data.get("draws", 0)),
                "h2h_matches": int(data.get("team1_wins", 0)) + int(data.get("team2_wins", 0)) + int(data.get("draws", 0)),
                "insight": data.get("insight", ""),
                "source": "ai_nvidia"
            }

        return {}

    except Exception as e:
        logger.debug(f"AI H2H failed for {team1} vs {team2}: {e}")
        return {}


def research_match_ai(home: str, away: str, league: str = "") -> dict:
    """Research a full match with AI."""
    result = {
        "home_form": "",
        "away_form": "",
        "home_goals_scored": 1.3,
        "away_goals_scored": 1.2,
        "home_goals_conceded": 1.1,
        "away_goals_conceded": 1.2,
        "home_position": 0,
        "away_position": 0,
        "h2h_home_wins": 0,
        "h2h_draws": 0,
        "h2h_away_wins": 0,
        "h2h_matches": 0,
        "source": "ai_nvidia",
    }

    home_data = research_team_with_ai(home, league)
    away_data = research_team_with_ai(away, league)
    h2h_data = research_h2h_with_ai(home, away)

    if home_data:
        result.update({
            "home_form": home_data.get("form", ""),
            "home_goals_scored": home_data.get("goals_scored", 1.3),
            "home_goals_conceded": home_data.get("goals_conceded", 1.2),
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
            "h2h_home_wins": h2h_data.get("h2h_home_wins", 0),
            "h2h_draws": h2h_data.get("h2h_draws", 0),
            "h2h_away_wins": h2h_data.get("h2h_away_wins", 0),
            "h2h_matches": h2h_data.get("h2h_matches", 0),
        })

    return result
