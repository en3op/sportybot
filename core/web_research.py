"""
Web Research Module
==================
Uses web search to get team form, recent results, H2H records.
"""

import logging
import re
import subprocess

logger = logging.getLogger(__name__)


def search_team_form(team: str, league: str = "") -> dict:
    """Search for team form using web search."""
    try:
        query = f"{team} {league} football last 5 matches results form WDL"
        if not league:
            query = f"{team} football team last 5 matches form results"
        
        result = subprocess.run(
            ["python", "-c", f"""
import sys
sys.path.insert(0, 'C:/Users/EN3OP/.opencode/tools')
from websearch import websearch
results = websearch(query='{query}', numResults=3)
text = ' '.join([r.get('text', '')[:500] for r in results])
print(text[:2000])
"""],
            capture_output=True, text=True, timeout=30, cwd="C:/Users/EN3OP/Desktop/sportybot"
        )
        
        text = result.stdout if result.returncode == 0 else ""
        return _parse_form_results(text)
        
    except Exception as e:
        logger.debug(f"Search failed for {team}: {e}")
        return {}


def search_h2h(team1: str, team2: str) -> dict:
    """Search for head-to-head record between two teams."""
    try:
        query = f"{team1} vs {team2} head to head record last 10 meetings results"
        
        result = subprocess.run(
            ["python", "-c", f"""
import sys
sys.path.insert(0, 'C:/Users/EN3OP/.opencode/tools')
from websearch import websearch
results = websearch(query='{query}', numResults=3)
text = ' '.join([r.get('text', '')[:500] for r in results])
print(text[:2000])
"""],
            capture_output=True, text=True, timeout=30, cwd="C:/Users/EN3OP/Desktop/sportybot"
        )
        
        text = result.stdout if result.returncode == 0 else ""
        return _parse_h2h_results(text)
        
    except Exception as e:
        logger.debug(f"H2H search failed for {team1} vs {team2}: {e}")
        return {}


def _parse_form_results(text: str) -> dict:
    """Parse team form from search results."""
    result = {"form": "", "goals_scored": 1.3, "goals_conceded": 1.1, "position": 0}
    
    text_lower = text.lower()
    
    form_patterns = [
        r'form[:\s]+([wlwd]{5})',
        r'last\s*5[:\s]*([wlwd]{5})',
        r'recent\s*form[:\s]+([wlwd]{5})',
        r'([wlwd]{5})\s*record',
    ]
    
    for pattern in form_patterns:
        match = re.search(pattern, text_lower)
        if match:
            result["form"] = match.group(1).upper()
            break
    
    goals_patterns = [
        r'(\d+\.?\d*)\s*goals?\s*per\s*game',
        r'avg\s*(\d+\.?\d*)\s*goals',
        r'scoring\s*(\d+\.?\d*)\s*per',
    ]
    
    for pattern in goals_patterns:
        match = re.search(pattern, text_lower)
        if match:
            result["goals_scored"] = float(match.group(1))
            break
    
    position_match = re.search(r'position\s*#?(\d+)', text_lower)
    if position_match:
        result["position"] = int(position_match.group(1))
    
    return result


def _parse_h2h_results(text: str) -> dict:
    """Parse H2H record from search results."""
    result = {"home_wins": 0, "draws": 0, "away_wins": 0, "total": 0}
    
    text_lower = text.lower()
    
    all_matches = re.findall(r'(\d+)\s*-\s*(\d+)', text)
    if all_matches:
        result["total"] = min(len(all_matches), 10)
        home_w = sum(1 for a, b in all_matches if int(a) > int(b))
        away_w = sum(1 for a, b in all_matches if int(b) > int(a))
        draws = sum(1 for a, b in all_matches if int(a) == int(b))
        result["home_wins"] = home_w
        result["away_wins"] = away_w
        result["draws"] = draws
    
    record_match = re.search(r'(\d+)\s*wins?\s*.*?\s*(\d+)\s*wins?', text_lower)
    if record_match:
        result["home_wins"] = int(record_match.group(1))
        result["away_wins"] = int(record_match.group(2))
    
    return result
