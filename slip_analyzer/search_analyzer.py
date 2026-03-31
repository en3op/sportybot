"""
Search-Based Slip Analyzer
==========================
Analyzes betting slips using live DuckDuckGo search for each match.
Returns verdicts (KEEP/RISKY/DROP) based on real-time form and prediction data.
Uses NVIDIA NIM API for AI analysis.
"""

import json
import time
import logging
import os
import re
from datetime import datetime
from typing import Optional

from duckduckgo_search import DDGS
try:
    from ddgs import DDGS as DDGS2
    USE_DDGS = True
except ImportError:
    USE_DDGS = False

logger = logging.getLogger(__name__)

# ── NVIDIA NIM API CONFIG ───────────────────────────────────────────────────

NVIDIA_API_KEY = os.environ.get("NVIDIA_API_KEY", "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")
NVIDIA_MODEL = "z-ai/glm5"  # GLM-5 for football analysis


def get_nvidia_client():
    """Get NVIDIA NIM API client."""
    try:
        from openai import OpenAI
        return OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY
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


# ── CACHED SEARCH WITH RETRY ────────────────────────────────────────────────

def search_match_with_retry(home: str, away: str, max_retries: int = 3) -> dict:
    """
    Search for match context with caching and retry logic.
    
    Returns:
        dict with: tier, form_home, form_away, search_context, verdict, etc.
    """
    from .match_search_cache import get_cache
    from .tier_classifier import classify_match_tier
    
    cache = get_cache()
    
    # Check cache first
    cached = cache.get(home, away)
    if cached:
        return cached
    
    # Search with retry
    search_context = ""
    for attempt in range(max_retries):
        try:
            search_context = search_match_context(home, away)
            if search_context and "failed" not in search_context.lower():
                break
        except Exception as e:
            logger.warning(f"Search attempt {attempt+1} failed for {home} vs {away}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2)
    
    # Extract form data from search context
    form_home, form_away = _extract_form_from_context(search_context)
    
    # Classify tier (will use odds data separately)
    tier = "C"  # Default, will be refined with odds
    
    # Determine verdict based on search context
    verdict = _determine_verdict(search_context, form_home, form_away)
    
    # Build result
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
        "search_context": search_context[:500] if search_context else "",
        "analysis_summary": _summarize_context(search_context),
        "verdict": verdict,
        "source": "search"
    }
    
    # Cache the result
    cache.set(home, away, result)
    
    return result


def search_matches_batch(matches: list, progress_callback=None) -> dict:
    """
    Search multiple matches sequentially with progress reporting.
    
    Args:
        matches: List of dicts with 'home' and 'away' team names
        progress_callback: Optional callback(current, total, match_key)
    
    Returns:
        dict keyed by "home vs away" with search results
    """
    results = {}
    total = len(matches)
    
    for idx, match in enumerate(matches):
        home = match.get("home", match.get("home_team", ""))
        away = match.get("away", match.get("away_team", ""))
        
        if not home or not away:
            continue
        
        match_key = f"{home} vs {away}"
        
        # Report progress
        if progress_callback:
            progress_callback(idx + 1, total, match_key)
        
        # Search with retry
        result = search_match_with_retry(home, away)
        results[match_key] = result
        
        # Rate limiting
        if idx < total - 1:
            time.sleep(1)
    
    return results


def _extract_form_from_context(context: str) -> tuple:
    """Extract form strings from search context."""
    import re
    
    form_home = ""
    form_away = ""
    
    if not context:
        return form_home, form_away
    
    # Look for form patterns like "WWLDW" or "W D L W W"
    form_pattern = re.compile(r'\b[WDL]{3,5}\b')
    forms = form_pattern.findall(context.upper())
    
    if len(forms) >= 2:
        form_home = forms[0]
        form_away = forms[1]
    elif len(forms) == 1:
        form_home = forms[0]
    
    return form_home, form_away


def _determine_verdict(context: str, form_home: str, form_away: str) -> str:
    """Determine KEEP/RISKY/DROP verdict from context."""
    if not context or "failed" in context.lower():
        return "RISKY"
    
    context_lower = context.lower()
    
    # Positive indicators
    positive = ["win", "favorite", "strong", "good form", "unbeaten", "dominant"]
    # Negative indicators
    negative = ["loss", "lose", "poor", "struggling", "injured", "suspend"]
    
    pos_count = sum(1 for p in positive if p in context_lower)
    neg_count = sum(1 for n in negative if n in context_lower)
    
    # Form check
    if form_home:
        home_wins = form_home.count("W")
        if home_wins >= 3:
            pos_count += 2
        elif home_wins <= 1:
            neg_count += 1
    
    if pos_count >= 2 and neg_count == 0:
        return "KEEP"
    elif neg_count >= 2:
        return "DROP"
    else:
        return "RISKY"


def _summarize_context(context: str) -> str:
    """Create a brief summary of search context."""
    if not context:
        return "No data found"
    
    # Extract key phrases
    lines = context.split("\n")
    summary_parts = []
    
    for line in lines[:3]:
        if len(line) > 10 and "source" not in line.lower():
            # Truncate long lines
            summary = line[:80] + "..." if len(line) > 80 else line
            summary_parts.append(summary)
    
    return " | ".join(summary_parts[:2]) if summary_parts else "Limited data"

# ── PROMPT 1: EXTRACTION ────────────────────────────────────────────────────

EXTRACTION_PROMPT = """
Extract all football matches from this OCR text and return ONLY a JSON array.
No explanation, no markdown, no backticks. Just raw JSON.

Each object must have:
{
  "match_id": 1,
  "home_team": "Full team name",
  "away_team": "Full team name",
  "market": "1X2 or BTTS or Over 2.5 or Under 2.5 etc",
  "odds": 1.85,
  "user_pick": "Home or Away or Draw or Yes or No or Over or Under"
}

Rules:
- Normalize short names (Man Utd → Manchester United, B. Munich → Bayern Munich)
- If odds not visible set to null
- Infer market if unclear (1 = Home win, 2 = Away win, X = Draw)
- If less than 2 matches found return exactly: {"error": "unclear_image"}

OCR TEXT:
{ocr_text}
"""

# ── SEARCH FUNCTION ─────────────────────────────────────────────────────────

def search_match_context(home: str, away: str) -> str:
    """Search DuckDuckGo for form and prediction data for a fixture."""
    month_year = datetime.now().strftime("%B %Y")
    query = f"{home} vs {away} form prediction {month_year}"
    
    try:
        if USE_DDGS:
            with DDGS2() as ddgs:
                results = list(ddgs.text(query, max_results=3))
                if not results:
                    return "No search results found."
                
                context = ""
                for i, r in enumerate(results, 1):
                    context += f"Source {i}: {r.get('title', '')}\n"
                    context += f"{r.get('body', '')}\n\n"
                
                return context.strip()
        else:
            with DDGS() as ddgs:
                results = ddgs.text(query, max_results=3)
                if not results:
                    return "No search results found."
                
                context = ""
                for i, r in enumerate(results, 1):
                    context += f"Source {i}: {r.get('title', '')}\n"
                    context += f"{r.get('body', '')}\n\n"
                
                return context.strip()
    except Exception as e:
        logger.warning(f"Search failed for {home} vs {away}: {e}")
        return f"Search failed: {str(e)}"


def build_search_context(matches: list) -> dict:
    """Run a search for every match and return a dict keyed by match_id."""
    context_map = {}
    for match in matches:
        match_id = match.get("match_id", 0)
        home = match.get("home_team", "")
        away = match.get("away_team", "")
        
        if not home or not away:
            continue
            
        logger.info(f"Searching: {home} vs {away}...")
        context_map[match_id] = search_match_context(home, away)
        time.sleep(1)  # Avoid rate limiting
    
    return context_map


# ── PROMPT 2: ANALYSIS WITH CONTEXT ─────────────────────────────────────────

def build_analysis_prompt(matches: list, context_map: dict) -> str:
    context_block = ""
    for match in matches:
        mid = match.get("match_id", 0)
        home = match.get("home_team", "Unknown")
        away = match.get("away_team", "Unknown")
        market = match.get("market", "Unknown")
        odds = match.get("odds", "N/A")
        user_pick = match.get("user_pick", "Unknown")
        
        context_block += f"""
Match {mid}: {home} vs {away}
Market: {market} | Pick: {user_pick} | Odds: {odds}
Live Search Context:
{context_map.get(mid, 'No data found')}
{"─" * 50}
"""
    
    return f"""
You are a football betting slip analyzer for a Telegram bot.
You have been given live search data for each match in the user's betting slip.

Use the search context as your PRIMARY source. Only use training knowledge if search context is empty or unclear.

## MATCHES AND LIVE CONTEXT:
{context_block}

## YOUR TASK:
Analyze each match and return a verdict using this logic:
- KEEP ✅ — Form + H2H support the pick, odds are fair
- RISKY ⚠️ — One factor goes against the pick
- DROP ❌ — Two or more factors go against the pick

If search context has no useful data for a match, say: "Limited data found — verify independently" and mark as RISKY.

## STRICT RULES:
- Never fabricate specific stats (e.g. "won 4 of last 5") unless confirmed in search context
- Keep reasons to one sentence per leg
- Always show the upgrade CTA at the end

## OUTPUT FORMAT (use exactly):

🧾 *SLIP ANALYSIS*

[For each match:]
1. *[Home] vs [Away]* — [Market] @ [Odds]
Verdict: [KEEP ✅ / RISKY ⚠️ / DROP ❌]
Reason: [One sentence using search context]

---

📊 *Overall: [Strong Slip ✅ / Decent Slip ⚠️ / Weak Slip ❌]*
[One line summary]

⚡ *Want me to fix the risky legs and rebuild this slip with better picks?*
*Upgrade to VIP 👉 [link]*
"""


# ── TEAM NAME NORMALIZATION ────────────────────────────────────────────────

TEAM_NORMALIZATIONS = {
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "man city": "Manchester City",
    "b. munich": "Bayern Munich",
    "bayern": "Bayern Munich",
    "psg": "Paris Saint-Germain",
    "real": "Real Madrid",
    "barca": "Barcelona",
    "atletico": "Atletico Madrid",
    "inter": "Inter Milan",
    "ac milan": "Milan",
    "tottenham": "Tottenham Hotspur",
    "spurs": "Tottenham Hotspur",
    "newcastle": "Newcastle United",
    "brighton": "Brighton & Hove Albion",
    "west ham": "West Ham United",
    "aston villa": "Aston Villa",
    "wolves": "Wolverhampton Wanderers",
    "nottingham": "Nottingham Forest",
    "forest": "Nottingham Forest",
    "leicester": "Leicester City",
    "everton": "Everton",
    "fulham": "Fulham",
    "crystal palace": "Crystal Palace",
    "bournemouth": "AFC Bournemouth",
    "brentford": "Brentford",
    "liverpool": "Liverpool",
    "chelsea": "Chelsea",
    "arsenal": "Arsenal",
    "juventus": "Juventus",
    "napoli": "Napoli",
    "roma": "AS Roma",
    "lazio": "Lazio",
    "dortmund": "Borussia Dortmund",
    "leipzig": "RB Leipzig",
    "leverkusen": "Bayer Leverkusen",
    "frankfurt": "Eintracht Frankfurt",
    "monaco": "AS Monaco",
    "marseille": "Olympique Marseille",
    "lyon": "Olympique Lyon",
    "ajax": "Ajax",
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


# ── OCR PARSER (Fallback) ───────────────────────────────────────────────────

def parse_ocr_to_matches(ocr_text: str) -> list[dict]:
    """Parse OCR text into match objects without AI."""
    matches = []
    lines = ocr_text.strip().split('\n')
    
    # Patterns for different formats
    vs_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s\.]+?)\s+(?:vs?\.?|v|-)\s+([A-Za-z][A-Za-z\s\.]+?)(?:\s+|$)"
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
            
            # Try to extract odds
            odds_match = odds_pattern.search(line)
            odds = float(odds_match.group(1)) if odds_match else None
            
            # Infer market from odds
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


# ── PROMPT 3: AI BEST PLAY PREDICTION ──────────────────────────────────────

AI_PREDICTION_PROMPT = """
You are an expert football betting analyst. Analyze the following search data for a match and suggest the 3 best "plays" (Market + Pick) for this game.

## FIXTURE: {home} vs {away}
## SEARCH DATA:
{context}

## YOUR TASK:
Suggest exactly 3 plays for this match:
1. SAFE - Highest probability (e.g. Double Chance, Over 1.5, DNB). Target odds: 1.20 - 1.50.
2. MODERATE - Balanced value (e.g. 1X2 favorite, BTTS, Over 2.5). Target odds: 1.60 - 2.20.
3. HIGH - Aggressive play (e.g. Underdog win, Correct Score, 1X2 Draw). Target odds: 2.50 - 5.00.

For each play, you MUST estimate "Fair Odds" based on the probability you see in the data.

## OUTPUT FORMAT (JSON ONLY):
{{
  "safe": {{"market": "Match Result", "pick": "Home Win", "odds": 1.45, "confidence": 88, "reason": "..."}},
  "moderate": {{"market": "Goals", "pick": "Over 2.5", "odds": 1.85, "confidence": 72, "reason": "..."}},
  "high": {{"market": "Handicap", "pick": "Away -1", "odds": 3.40, "confidence": 45, "reason": "..."}}
}}
"""

def ai_predict_best_plays(home: str, away: str, context: str) -> dict:
    """Ask AI to suggest the best plays for a match based on search data."""
    if not context or "failed" in context.lower():
        return {}
    
    prompt = AI_PREDICTION_PROMPT.format(home=home, away=away, context=context[:2000])
    ai_result = call_nvidia_ai(prompt, max_tokens=800)
    
    if ai_result:
        try:
            # Clean up potential markdown
            raw = ai_result.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
                if raw.startswith("json"):
                    raw = raw[4:].strip()
            return json.loads(raw)
        except Exception as e:
            logger.warning(f"Failed to parse AI predictions for {home} vs {away}: {e}")
    
    return {}


# ── MAIN ORCHESTRATOR ────────────────────────────────────────────────────────

def analyze_slip_with_search(ocr_text: str, glm_client=None) -> str:
    """
    Full pipeline:
    1. Extract matches from OCR text (with AI if available, else regex)
    2. Search each fixture on DuckDuckGo
    3. Analyze with context using AI (NVIDIA or GLM)
    4. Return final message
    """
    # Step 1: Extract matches
    matches = None

    # Try AI extraction with NVIDIA first
    if not glm_client:
        extraction_prompt = EXTRACTION_PROMPT.replace("{ocr_text}", ocr_text)
        ai_result = call_nvidia_ai(extraction_prompt, max_tokens=500)
        if ai_result:
            try:
                # Clean up potential markdown
                raw = ai_result.strip()
                if raw.startswith("```"):
                    raw = raw.strip("`").strip()
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                matches = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("NVIDIA extraction returned non-JSON, using regex")
    
    if glm_client:
        try:
            extraction_response = glm_client.chat.completions.create(
                model="glm-4v",
                messages=[{
                    "role": "user",
                    "content": EXTRACTION_PROMPT.replace("{ocr_text}", ocr_text)
                }]
            )
            raw = extraction_response.choices[0].message.content.strip()

            # Clean up potential markdown
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

            matches = json.loads(raw)
        except Exception as e:
            logger.warning(f"AI extraction failed: {e}")

    # Fallback to regex parsing
    if not matches:
        matches = parse_ocr_to_matches(ocr_text)

    # Handle unclear image
    if isinstance(matches, dict) and matches.get("error") == "unclear_image":
        return "❌ I couldn't detect enough matches. Please send a clearer screenshot."

    if not matches or len(matches) < 2:
        return "❌ I could only find one match. Please send the full slip screenshot."

    # Step 2: Search each fixture
    context_map = build_search_context(matches)

    # Step 3: Build analysis prompt with context
    analysis_prompt = build_analysis_prompt(matches, context_map)

    # Step 4: Get AI analysis with full context
    # Try NVIDIA AI first
    ai_result = call_nvidia_ai(analysis_prompt, max_tokens=1500)
    if ai_result:
        return ai_result

    # Try GLM if available
    if glm_client:
        try:
            analysis_response = glm_client.chat.completions.create(
                model="glm-4v",
                messages=[{
                    "role": "user",
                    "content": analysis_prompt
                }]
            )
            return analysis_response.choices[0].message.content
        except Exception as e:
            logger.error(f"GLM analysis failed: {e}")

    # Fallback: return search-based analysis without AI
    return build_fallback_response(matches, context_map)


def build_fallback_response(matches: list, context_map: dict) -> str:
    """Build response when AI is unavailable."""
    lines = ["🧾 *SLIP ANALYSIS*\n"]
    
    for m in matches:
        mid = m.get("match_id", 0)
        home = m.get("home_team", "Unknown")
        away = m.get("away_team", "Unknown")
        market = m.get("market", "Unknown")
        odds = m.get("odds", "N/A")
        user_pick = m.get("user_pick", "Unknown")
        context = context_map.get(mid, "No data")
        
        lines.append(f"{mid}. *{home} vs {away}* — {market} @ {odds}")
        
        # Simple heuristic based on search context
        context_lower = context.lower()
        if "win" in context_lower or "favorite" in context_lower:
            verdict = "KEEP ✅"
        elif "risk" in context_lower or "uncertain" in context_lower:
            verdict = "RISKY ⚠️"
        else:
            verdict = "RISKY ⚠️"
        
        lines.append(f"Verdict: {verdict}")
        lines.append(f"Reason: Based on search context (AI unavailable)")
        lines.append("---\n")
    
    lines.append("📊 *Overall: Verify picks manually*")
    lines.append("")
    lines.append("⚡ *Upgrade to VIP for AI-powered analysis 👉 /vip*")
    
    return "\n".join(lines)
