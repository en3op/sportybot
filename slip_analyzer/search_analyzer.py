""" 
Search-Based Slip Analyzer 
========================== 
Analyzes betting slips using DuckDuckGo search for match data. 
Returns 3 slip tiers (SAFE/MODERATE/HIGH) based on the user's matches only.
Uses NVIDIA NIM API for AI analysis. 
""" 

import json 
import time 
import logging 
import os 
import re 
from datetime import datetime 
from typing import Optional 
from concurrent.futures import ThreadPoolExecutor, as_completed

logger = logging.getLogger(__name__) 

USE_DDGS = True 
USE_TAVILY = False

# ── NVIDIA NIM API CONFIG ───────────────────────────────────────────────────

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "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")
NVIDIA_MODEL = "z-ai/glm5"  # GLM-5 for football analysis


def get_nvidia_client():
    """Get NVIDIA NIM API client."""
    try:
        from openai import OpenAI
        return OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY,
            timeout=60.0,
            max_retries=2
        )
    except Exception as e:
        logger.warning(f"Could not initialize NVIDIA client: {e}")
        return None


def call_nvidia_ai(prompt: str, max_tokens: int = 1000) -> Optional[str]:
    """Call NVIDIA NIM API with a prompt."""
    client = get_nvidia_client()
    if not client:
        return None

    try:
        response = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"NVIDIA API call failed: {e}")
        return None


def search_match_with_retry(home: str, away: str, max_retries: int = 1) -> dict:
    """
    Search for match context with caching.
    """
    from .match_search_cache import get_cache

    cache = get_cache()
    cached = cache.get(home, away)
    if cached:
        return cached

    search_context = search_match_context(home, away)
    form_home, form_away = _extract_form_from_context(search_context)
    tier = "C"
    verdict = _determine_verdict(search_context, form_home, form_away)

    result = {
        "home_team": home,
        "away_team": away,
        "tier": tier,
        "form_home": form_home,
        "form_away": form_away,
        "position_home": 0,
        "position_away": 0,
        "goals_home": 0.0,
        "goals_away": 0.0,
        "search_context": search_context,
        "verdict": verdict,
    }
    cache.put(home, away, result)
    return result


def search_match_context(home: str, away: str) -> str:
    """Search DuckDuckGo for form and prediction data for a fixture."""
    query = f"{home} vs {away} football form results 2024 2025"
    try:
        if USE_TAVILY:
            from tavily import TavilyClient
            client = TavilyClient(api_key=os.environ.get("TAVILY_API_KEY", ""))
            results = client.search(query, max_results=3)
            return " ".join([r.get("content", "") for r in results.get("results", [])])
    except Exception:
        pass

    if USE_DDGS:
        try:
            from ddgs import DDGS as DDGS2
            with DDGS2() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                return " ".join([r.get("body", "") for r in results])
        except Exception:
            try:
                from duckduckgo_search import DDGS
                with DDGS() as ddgs:
                    results = ddgs.text(query, max_results=3)
                    return " ".join([r.get("body", "") for r in results])
            except Exception as e:
                logger.warning(f"DDGS search failed for {home} vs {away}: {e}")
    return f"Search failed for {home} vs {away}"


def _extract_form_from_context(context: str) -> tuple:
    """Extract form strings from search context."""
    form_home = "Unknown"
    form_away = "Unknown"
    
    form_patterns = [
        r'([WDLLwdl]{3,10})\s*[-–]\s*([WDLLwdl]{3,10})',
        r'(?:form|last 5|last 6)\s*[:\-]\s*([A-Za-z]{3,10})',
        r'([A-Za-z]{3,10})\s*(?:form|last)',
    ]
    
    for pattern in form_patterns:
        match = re.search(pattern, context, re.IGNORECASE)
        if match:
            if match.lastindex and match.lastindex >= 2:
                form_home = match.group(1).upper()
                form_away = match.group(2).upper()
            else:
                form_home = match.group(1).upper()
            break
    
    return form_home, form_away


def _determine_verdict(context: str, form_home: str, form_away: str) -> str:
    """Determine a simple verdict based on search context."""
    context_lower = context.lower()
    if "win" in context_lower or "favorite" in context_lower:
        return "KEEP"
    elif "risk" in context_lower or "uncertain" in context_lower:
        return "RISKY"
    return "RISKY"


# ── OCR PARSER ──────────────────────────────────────────────────────────────

TEAM_NORMALIZATIONS = {
    "man city": "Manchester City",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "tottenham": "Tottenham Hotspur",
    "spurs": "Tottenham Hotspur",
    "wolves": "Wolverhampton Wanderers",
    "newcastle": "Newcastle United",
    "west ham": "West Ham United",
    "nottm forest": "Nottingham Forest",
    "forest": "Nottingham Forest",
    "bournemouth": "AFC Bournemouth",
    "aston villa": "Aston Villa",
    "crystal palace": "Crystal Palace",
    "palace": "Crystal Palace",
    "brighton": "Brighton & Hove Albion",
    "fulham": "Fulham FC",
    "brentford": "Brentford FC",
    "everton": "Everton FC",
    "leicester": "Leicester City",
    "ipswich": "Ipswich Town",
    "southampton": "Southampton FC",
    "barcelona": "FC Barcelona",
    "real madrid": "Real Madrid CF",
    "atletico": "Atletico Madrid",
    "atletico madrid": "Atletico Madrid",
    "bayern": "Bayern Munich",
    "bayern munich": "Bayern Munich",
    "dortmund": "Borussia Dortmund",
    "leverkusen": "Bayer Leverkusen",
    "psg": "Paris Saint-Germain",
    "paris sg": "Paris Saint-Germain",
    "juventus": "Juventus FC",
    "inter": "Inter Milan",
    "inter milan": "Inter Milan",
    "ac milan": "AC Milan",
    "milan": "AC Milan",
    "roma": "AS Roma",
    "lazio": "SS Lazio",
    "ajax": "AFC Ajax",
    "feyenoord": "Feyenoord",
    "psv": "PSV Eindhoven",
    "benfica": "SL Benfica",
    "porto": "FC Porto",
    "sporting": "Sporting CP",
    "celtic": "Celtic",
    "rangers": "Rangers",
}

def normalize_team_name(name: str) -> str:
    """Normalize short team names to full names."""
    if not name:
        return name
    name_lower = name.lower().strip()
    for short, full in TEAM_NORMALIZATIONS.items():
        if short in name_lower or name_lower in short:
            return full
    return name.strip()


def parse_ocr_to_matches(ocr_text: str) -> list[dict]:
    """Parse OCR text into match objects without AI."""
    matches = []
    lines = ocr_text.strip().split('\n')
    
    vs_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s\.]+?)\s+(?:vs?\.?|v|[-–])\s+([A-Za-z][A-Za-z\s\.]+?)(?:\s+|$)"
    )
    odds_pattern = re.compile(r"(\d+\.\d{1,2})")
    
    match_id = 0
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        vs_match = vs_pattern.search(line)
        if vs_match:
            home = normalize_team_name(vs_match.group(1))
            away = normalize_team_name(vs_match.group(2))
            
            odds_match = odds_pattern.search(line)
            odds = float(odds_match.group(1)) if odds_match else None
            
            market = "1X2"
            user_pick = "Home"
            
            if odds and odds < 1.5:
                market = "1X2"
                user_pick = "Home"
            elif odds and odds > 3.0:
                market = "1X2"
                user_pick = "Away"
            
            match_id += 1
            matches.append({
                "match_id": match_id,
                "home_team": home,
                "away_team": away,
                "market": market,
                "odds": odds,
                "user_pick": user_pick,
            })
    
    return matches


# ── AI PROMPT FOR 3 SLIPS ──────────────────────────────────────────────────

THREE_SLIPS_PROMPT = """
You are an expert football betting analyst. The user has sent a betting slip with these matches:

{matches_text}

## SEARCH DATA FOR EACH MATCH:
{search_data}

## YOUR TASK:
Based on the search data above, analyze each match and create EXACTLY 3 slip tiers using ONLY these matches:

1. **🔒 SAFE SLIP** — Low risk, high probability picks from these matches
   - Use Double Chance, Over 1.5 Goals, Draw No Bet markets
   - Target odds per pick: 1.10 - 1.80
   - Pick the safest option from each match

2. **⚖️ MODERATE SLIP** — Balanced risk/reward from these matches
   - Use 1X2, BTTS, Over 2.5 Goals markets
   - Target odds per pick: 1.50 - 2.50
   - Pick the best value option from each match

3. **🚀 HIGH SLIP** — High risk, high reward from these matches
   - Use 1X2 straight, Correct Score, Handicap markets
   - Target odds per pick: 2.00 - 5.00
   - Pick the most aggressive option from each match

For each match, suggest ONE pick per tier. All picks must come from the user's matches only.

## OUTPUT FORMAT (JSON ONLY):
{{
  "safe": {{
    "picks": [
      {{"match": "Team A vs Team B", "market": "Double Chance", "pick": "1X", "odds": 1.30, "confidence": 85, "reason": "Team A unbeaten at home"}}
    ],
    "total_odds": 1.69,
    "description": "Safe accumulator"
  }},
  "moderate": {{
    "picks": [...],
    "total_odds": 4.50,
    "description": "Moderate accumulator"
  }},
  "high": {{
    "picks": [...],
    "total_odds": 12.00,
    "description": "High risk accumulator"
  }}
}}
"""


def build_slip_analysis_prompt(matches: list, context_map: dict) -> str:
    """Build prompt for AI to create 3 slip tiers."""
    matches_text = ""
    for m in matches:
        mid = m.get("match_id", 0)
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        market = m.get("market", "1X2")
        odds = m.get("odds", "N/A")
        matches_text += f"{mid}. {home} vs {away} — {market} @ {odds}\n"
    
    search_data = ""
    for m in matches:
        mid = m.get("match_id", 0)
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        ctx = context_map.get(mid, "No search data available")
        search_data += f"\n### {home} vs {away}:\n{ctx[:500]}\n"
    
    return THREE_SLIPS_PROMPT.format(matches_text=matches_text, search_data=search_data)


def format_three_slips_response(ai_response: str) -> str:
    """Format AI response into Telegram-friendly 3 slips."""
    try:
        raw = ai_response.strip()
        if raw.startswith("```"):
            raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()
        data = json.loads(raw)
    except Exception:
        return None
    
    lines = ["🧾 *SLIP ANALYSIS*\n"]
    
    # Safe slip
    safe = data.get("safe", {})
    safe_picks = safe.get("picks", [])
    safe_total = safe.get("total_odds", 0)
    if safe_picks:
        lines.append("🔒 *SAFE SLIP* (Low Risk)")
        for p in safe_picks:
            lines.append(f"• {p.get('match', '')}: {p.get('market', '')} → {p.get('pick', '')} @ {p.get('odds', 0):.2f}")
        lines.append(f"Total Odds: {safe_total:.2f}\n")
    
    # Moderate slip
    mod = data.get("moderate", {})
    mod_picks = mod.get("picks", [])
    mod_total = mod.get("total_odds", 0)
    if mod_picks:
        lines.append("⚖️ *MODERATE SLIP* (Medium Risk)")
        for p in mod_picks:
            lines.append(f"• {p.get('match', '')}: {p.get('market', '')} → {p.get('pick', '')} @ {p.get('odds', 0):.2f}")
        lines.append(f"Total Odds: {mod_total:.2f}\n")
    
    # High slip
    high = data.get("high", {})
    high_picks = high.get("picks", [])
    high_total = high.get("total_odds", 0)
    if high_picks:
        lines.append("🚀 *HIGH SLIP* (High Risk)")
        for p in high_picks:
            lines.append(f"• {p.get('match', '')}: {p.get('market', '')} → {p.get('pick', '')} @ {p.get('odds', 0):.2f}")
        lines.append(f"Total Odds: {high_total:.2f}\n")
    
    lines.append("⚡ *Want unlimited analysis?* Upgrade to VIP 👉 @Sporty_vip_bot")
    
    return "\n".join(lines)


def build_fallback_slips(matches: list, context_map: dict) -> str:
    """Build fallback 3 slips when AI is unavailable."""
    lines = ["🧾 *SLIP ANALYSIS*\n"]
    
    lines.append("🔒 *SAFE SLIP* (Low Risk)")
    for m in matches:
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        lines.append(f"• {home} vs {away}: Double Chance 1X @ 1.30")
    lines.append("")
    
    lines.append("⚖️ *MODERATE SLIP* (Medium Risk)")
    for m in matches:
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        lines.append(f"• {home} vs {away}: Over 2.5 Goals @ 1.80")
    lines.append("")
    
    lines.append("🚀 *HIGH SLIP* (High Risk)")
    for m in matches:
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        lines.append(f"• {home} vs {away}: 1X2 Home Win @ 2.20")
    lines.append("")
    
    lines.append("⚡ *Want AI-powered analysis?* Upgrade to VIP 👉 @Sporty_vip_bot")
    
    return "\n".join(lines)


# ── MAIN ORCHESTRATOR ────────────────────────────────────────────────────────

def analyze_slip_with_search(ocr_text: str, glm_client=None) -> str:
    """
    Full pipeline:
    1. Extract matches from text (regex only, no AI)
    2. Search each fixture via DuckDuckGo (parallel)
    3. Use AI to create 3 slip tiers
    4. Return formatted response
    """
    # Step 1: Extract matches with regex (no AI)
    matches = parse_ocr_to_matches(ocr_text)

    if isinstance(matches, dict) and matches.get("error") == "unclear_image":
        return "❌ I couldn't detect enough matches. Please send a clearer slip."

    if not matches or len(matches) < 2:
        return "❌ I could only find one match. Please send the full slip."

    # Step 2: Search each fixture (parallel)
    context_map = build_search_context(matches)

    # Step 3: Build prompt and call AI
    prompt = build_slip_analysis_prompt(matches, context_map)
    ai_response = call_nvidia_ai(prompt, max_tokens=2000)

    # Step 4: Format response
    if ai_response:
        formatted = format_three_slips_response(ai_response)
        if formatted:
            return formatted
    
    # Fallback
    return build_fallback_slips(matches, context_map)


def build_search_context(matches: list) -> dict:
    """Build search context for all matches in parallel."""
    context_map = {}
    
    def search_one(m):
        mid = m.get("match_id", 0)
        home = m.get("home_team", "")
        away = m.get("away_team", "")
        ctx = search_match_context(home, away)
        return mid, ctx
    
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(search_one, m): m for m in matches}
        for future in as_completed(futures):
            try:
                mid, ctx = future.result()
                context_map[mid] = ctx
            except Exception as e:
                logger.warning(f"Search failed: {e}")
    
    return context_map
