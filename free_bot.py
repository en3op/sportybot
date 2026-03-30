"""
SportyBot - Free Betting Slip Analyzer Telegram Bot
====================================================
Users send a screenshot of their betting slip. The bot:
  1. Extracts text via Tesseract OCR
  2. Parses teams, bet types, and odds
  3. Fetches live match data from SportyBet API (cached + rate-limited)
  4. Cross-references user picks against real odds
  5. Flags risky picks and suggests safer alternatives
  6. Promotes VIP upgrade

Usage:
    pip install -r requirements.txt
    python free_bot.py
"""

import os
import re
import shutil
import logging
import tempfile
import asyncio
from datetime import datetime

from PIL import Image
import pytesseract

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from telegram.error import BadRequest

from sportybet_scraper import fetch_upcoming_events, analyze_all_markets_full
from infra.api_gateway import APIGateway
from research.cache.match_cache import MatchCache
from analysis_engine import (
    Pick, analyze_slip, format_telegram_message,
    classify_bet_risk, RiskLevel,
)
from slip_analyzer import analyze_slip as analyze_slip_v2
from slip_analyzer import analyze_slip_with_events, get_match_names
from slip_analyzer.search_analyzer import analyze_slip_with_search
from slip_analyzer.analyzer import analyze_slip_enhanced, get_full_analysis, cleanup_old_analyses

# =============================================================================
# CONFIGURATION
# =============================================================================

BOT_TOKEN = os.environ.get("FREE_BOT_TOKEN", "8784721708:AAFBp7_YbzpzeNvg-Y7lam_i8w6FhnJByHw")
PAYSTACK_LINK = os.environ.get("PAYSTACK_LINK", "https://paystack.com/pay/YOUR_PAYMENT_LINK_HERE")
TESSERACT_CMD = os.environ.get("TESSERACT_CMD")
if not TESSERACT_CMD:
    # Try common Windows path
    win_path = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    if os.path.exists(win_path):
        TESSERACT_CMD = win_path
    else:
        # Fallback for Linux/Docker
        TESSERACT_CMD = shutil.which("tesseract") or "tesseract"

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# =============================================================================
# INFRASTRUCTURE — Cache + API Gateway
# =============================================================================

# Two-tier cache: memory (L1) + SQLite (L2)
cache = MatchCache("cache.db")

# API Gateway with rate limiting + circuit breaker
gateway = APIGateway(cache_manager=cache, fallback_store=cache)
gateway.register_provider(
    "sportybet",
    rate_limit=8,          # max 8 requests
    per_seconds=60,        # per 60 seconds
    failure_threshold=3,   # open circuit after 3 failures
    recovery_timeout=30.0, # try again after 30s
)

# Cleanup expired cache entries on startup
cache.cleanup()

# =============================================================================
# OCR — Extract text from a betting slip image
# =============================================================================


def _configure_tesseract() -> None:
    """Set the Tesseract command path if configured."""
    if TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


def extract_text_from_image(image_path: str) -> str:
    """Run Tesseract OCR on an image file and return extracted text.
    
    Tries the best single approach first, falls back to binarized if empty.
    """
    _configure_tesseract()
    img = Image.open(image_path)
    img = img.convert("L")
    w, h = img.size
    if w < 1000:
        scale = 1000 / w
        img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

    # Primary: raw grayscale (best for dark-themed apps like SportyBet)
    try:
        text = pytesseract.image_to_string(img, config="--psm 4")
        if text.strip() and len(text.strip()) > 10:
            logger.info(f"OCR primary ({len(text)} chars): {text[:300]!r}")
            return text
    except Exception:
        pass

    # Fallback: binarized
    try:
        img2 = img.point(lambda x: 255 if x > 180 else 0, "1")
        text = pytesseract.image_to_string(img2, config="--psm 6")
        logger.info(f"OCR fallback ({len(text)} chars): {text[:300]!r}")
        return text
    except Exception:
        pass

    # Last resort
    text = pytesseract.image_to_string(img, config="--psm 6")
    logger.info(f"OCR last-resort ({len(text)} chars): {text[:300]!r}")
    return text


# =============================================================================
# SLIP PARSER — Extract picks and odds from OCR text
# =============================================================================


def parse_slip_text(text: str) -> list[dict]:
    """Parse OCR text to identify betting picks with odds.

    Supports SportyBet multi-line format:
        @) Draw 4.8
        South Sudan vs Djibouti
        1X2

    Also supports single-line formats like:
        Arsenal vs Chelsea @1.50
        Over 2.5 Goals @1.85
    """
    lines = text.strip().split("\n")
    lines = [l.strip() for l in lines if l.strip()]
    parsed = []
    used_indices = set()

    # ---- Single-line patterns ----
    match_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s\.]+?)\s+(?:vs?\.?|-)\s+([A-Za-z][A-Za-z\s\.]+?)\s+[@:\s]*\s*(\d+\.\d{1,2})",
    )
    goals_pattern = re.compile(
        r"(Over|Under|OV|UN)\s*(\d+\.5)\s*(?:Goals?)?\s*[@:\s]*\s*(\d+\.\d{1,2})",
        re.IGNORECASE,
    )
    btts_pattern = re.compile(
        r"(?:BTTS|Both\s+Teams?\s*(?:To\s+)?Score)\s*[-:]?\s*(Yes|No|Y|N)\s*[@:\s]*\s*(\d+\.\d{1,2})",
        re.IGNORECASE,
    )
    dc_pattern = re.compile(r"\b(1X|X2|12)\b\s*[@:\s]*\s*(\d+\.\d{1,2})")

    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        m = match_pattern.search(line)
        if m:
            parsed.append({
                "team1": m.group(1).strip().rstrip("."),
                "team2": m.group(2).strip().rstrip("."),
                "bet_type": "1X2",
                "odds": float(m.group(3)),
                "raw_line": line,
            })
            used_indices.add(i)
            continue
        g = goals_pattern.search(line)
        if g:
            direction = "Over" if g.group(1).lower() in ("over", "ov") else "Under"
            parsed.append({
                "team1": None, "team2": None,
                "bet_type": f"{direction} {g.group(2)}",
                "odds": float(g.group(3)),
                "raw_line": line,
            })
            used_indices.add(i)
            continue
        b = btts_pattern.search(line)
        if b:
            sel = "Yes" if b.group(1).lower() in ("yes", "y") else "No"
            parsed.append({
                "team1": None, "team2": None,
                "bet_type": f"BTTS {sel}",
                "odds": float(b.group(2)),
                "raw_line": line,
            })
            used_indices.add(i)
            continue
        dc = dc_pattern.search(line)
        if dc:
            parsed.append({
                "team1": None, "team2": None,
                "bet_type": f"Double Chance {dc.group(1)}",
                "odds": float(dc.group(2)),
                "raw_line": line,
            })
            used_indices.add(i)
            continue

    # ---- Multi-line SportyBet format ----
    sportybet_odds_pattern = re.compile(
        r"@\)?\s*(Home|Draw|Away)\s+(\d+\.\d{1,2})", re.IGNORECASE,
    )
    team_only_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s\.]+?)\s+(?:vs?\.?|-)\s+([A-Za-z][A-Za-z\s\.]+?)\s*$",
    )

    for i, line in enumerate(lines):
        if i in used_indices:
            continue
        od = sportybet_odds_pattern.search(line)
        if not od:
            continue
        bet_side = od.group(1).capitalize()
        odds = float(od.group(2))
        if bet_side == "Home":
            bet_type = "Home Win (1)"
        elif bet_side == "Away":
            bet_type = "Away Win (2)"
        else:
            bet_type = "Draw (X)"

        team1 = None
        team2 = None
        raw_lines = [line]
        for j in range(i + 1, min(i + 4, len(lines))):
            if j in used_indices:
                continue
            tm = team_only_pattern.search(lines[j])
            if tm:
                team1 = tm.group(1).strip().rstrip(".")
                team2 = tm.group(2).strip().rstrip(".")
                raw_lines.append(lines[j])
                used_indices.add(j)
                break
            if " vs " in lines[j].lower() or " v " in lines[j].lower():
                parts = re.split(r'\s+(?:vs?\.?|-)\s+', lines[j], maxsplit=1, flags=re.IGNORECASE)
                if len(parts) == 2:
                    team1 = parts[0].strip().rstrip(".")
                    team2 = parts[1].strip().rstrip(".")
                    raw_lines.append(lines[j])
                    used_indices.add(j)
                    break

        parsed.append({
            "team1": team1,
            "team2": team2,
            "bet_type": bet_type,
            "odds": odds,
            "raw_line": " | ".join(raw_lines),
        })
        used_indices.add(i)

    return parsed


# =============================================================================
# SPORTYBET LIVE DATA — via API Gateway with cache
# =============================================================================


def _fetch_events_raw() -> list[dict]:
    """Raw SportyBet API call with pagination. API max pageSize=100."""
    all_events = []
    for page in range(1, 4):  # Up to 3 pages (300 events max)
        events = fetch_upcoming_events(page_size=100, page_num=page, today_only=False)
        if not events:
            break
        all_events.extend(events)
    return all_events


async def fetch_live_events() -> list[dict]:
    """Fetch events through the API gateway (cached + rate-limited).

    Returns cached data if available (60s TTL for live odds).
    Falls back to cached data if API fails.
    """
    result = await gateway.call(
        "sportybet",
        cache_key="all_events",
        fetch_fn=_fetch_events_raw,
        cache_category="live_odds",
    )
    if result:
        logger.info(f"Got {len(result)} events (cache or API)")
        return result

    # Last resort: try direct call (bypass gateway)
    try:
        events = _fetch_events_raw()
        if events:
            # Cache for next time
            cache.set("all_events", events, "live_odds")
            return events
    except Exception as e:
        logger.error(f"Direct SportyBet call also failed: {e}")

    return []


def normalize_name(name: str) -> str:
    """Normalize a team name for matching."""
    name = name.lower().strip()
    # Remove common prefixes/suffixes
    for remove in ["asd", "scd", "ssd", "usd", "fc", "cf", "sc", "ac", "ud", "cd",
                   "bk", "if", "ff", "aif", "asd.", "ssd.", "scd.", "usd."]:
        name = re.sub(rf'\b{remove}\b\.?', '', name)
    name = re.sub(r'[^a-z\s]', '', name)
    return " ".join(name.split())


def _word_similarity(a: str, b: str) -> float:
    """Word-level Jaccard similarity between two strings."""
    wa = set(a.split())
    wb = set(b.split())
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def find_matching_event(team1: str, team2: str, events: list[dict]) -> dict | None:
    """Find a SportyBet event matching both teams with strict validation.

    Uses word-level Jaccard similarity on normalized names.
    Requires BOTH teams to match with >0.4 similarity to prevent false matches.
    """
    if not team1 or not team2:
        return None

    n1 = normalize_name(team1)
    n2 = normalize_name(team2)

    # Need at least 2 meaningful words per team after normalization
    if len(n1.split()) < 1 or len(n2.split()) < 1:
        return None

    best_match = None
    best_combined_score = 0.0

    for event in events:
        eh = normalize_name(event["home"])
        ea = normalize_name(event["away"])

        # Score both directions: (n1->home, n2->away) and (n1->away, n2->home)
        fwd = _word_similarity(n1, eh) + _word_similarity(n2, ea)
        rev = _word_similarity(n1, ea) + _word_similarity(n2, eh)
        score = max(fwd, rev)

        if score > best_combined_score:
            best_combined_score = score
            best_match = event

    # Require average similarity > 0.3 per team (0.6 combined) — relaxed for OCR
    if best_combined_score >= 0.6 and best_match:
        return best_match
    return None


# =============================================================================
# ANALYSIS ENGINE — Verdicts, value, accumulator risk
# =============================================================================


def _implied_prob(odds: float) -> float:
    """Convert decimal odds to implied probability (0-100)."""
    if odds <= 1.0:
        return 0.0
    return round(100.0 / odds, 1)


def analyze_single_pick(pick: dict, event: dict | None) -> dict:
    """Analyze a single pick with or without live market data.

    Returns enriched pick with verdict, risk flags, and alternatives.
    """
    bet = pick["bet_type"].lower()
    odds = pick["odds"]
    team1 = pick.get("team1")
    team2 = pick.get("team2")

    risk_flags = []
    risk_score = 0
    verdict = "KEEP"
    verdict_reason = ""
    alternatives = []

    # ---- Static odds-based analysis ----

    # High odds = high risk
    if odds > 5.0:
        risk_flags.append(f"Very high odds ({odds}) - unlikely to hit")
        risk_score += 3
    elif odds > 3.0:
        risk_flags.append(f"High odds ({odds}) - low probability")
        risk_score += 2
    elif odds > 2.0:
        risk_flags.append(f"Moderate odds ({odds})")
        risk_score += 1

    # Bet type risks
    if "over 2.5" in bet or "over 3.5" in bet:
        risk_flags.append("High goal line - harder to hit than Over 1.5")
        risk_score += 2
        alternatives.append("Over 1.5 Goals (higher hit rate)")
    if "btts" in bet:
        risk_flags.append("BTTS is volatile - depends on both teams scoring")
        risk_score += 1
    if "under 1.5" in bet:
        risk_flags.append("Very low scoring expectation")
        risk_score += 2
    if "draw" in bet:
        risk_flags.append("Draws are inherently unpredictable (~25% of matches)")
        risk_score += 1

    # Implied probability from user's odds
    user_prob = _implied_prob(odds)

    # ---- Live market data analysis ----
    live_data = None
    if event:
        eo = event.get("odds", {})
        home_o = eo.get("Home", 0)
        draw_o = eo.get("Draw", 0)
        away_o = eo.get("Away", 0)

        # Determine what user picked
        picked = None
        if "home" in bet or "1)" in bet:
            picked = "Home"
        elif "away" in bet or "2)" in bet:
            picked = "Away"
        elif "draw" in bet or "(x)" in bet:
            picked = "Draw"

        # Market probabilities
        probs = {}
        total = 0
        for lbl, o in [("Home", home_o), ("Draw", draw_o), ("Away", away_o)]:
            if o > 0:
                probs[lbl] = 1 / o
                total += probs[lbl]
        if total > 0:
            for k in probs:
                probs[k] = round(probs[k] / total * 100, 1)

        best = max(probs, key=probs.get) if probs else None
        best_prob = probs.get(best, 0)
        picked_prob = probs.get(picked, 0) if picked else 0
        picked_market_odds = {"Home": home_o, "Draw": draw_o, "Away": away_o}.get(picked, 0)

        # Value edge
        value_edge = 0
        if picked_market_odds > 0 and odds > 0:
            value_edge = round((odds / picked_market_odds - 1) * 100, 1)

        # Build labels
        home_name = event.get("home", "Home")
        away_name = event.get("away", "Away")
        labels = {"Home": f"{home_name} (1)", "Draw": "Draw (X)", "Away": f"{away_name} (2)"}

        live_data = {
            "event": event,
            "live_odds": {"Home": home_o, "Draw": draw_o, "Away": away_o},
            "implied_probs": probs,
            "picked": picked,
            "picked_prob": picked_prob,
            "market_best": best,
            "market_best_prob": best_prob,
            "value_edge": value_edge,
            "labels": labels,
        }

        # Verdict based on market data
        if picked and best and picked != best:
            if picked_prob < 25:
                verdict = "REMOVE"
                verdict_reason = f"Market says {labels[best]} ({best_prob}%) not {labels[picked]} ({picked_prob}%)"
                risk_score += 3
            elif picked_prob < 40 and best_prob > 50:
                verdict = "SWAP"
                verdict_reason = f"Market strongly favors {labels[best]} ({best_prob}%)"
                risk_score += 2
            else:
                verdict = "SWAP"
                verdict_reason = f"Market slightly prefers {labels[best]} ({best_prob}%) vs your {picked_prob}%"
                risk_score += 1
        elif picked and best and picked == best:
            if value_edge > 10:
                verdict = "KEEP"
                verdict_reason = f"Great value! You get +{value_edge}% edge over market odds"
            elif value_edge > 0:
                verdict = "KEEP"
                verdict_reason = f"Good value (+{value_edge}% edge), market agrees"
            else:
                verdict = "KEEP"
                verdict_reason = f"Market agrees ({best_prob}% implied)"

        # Build safer alternatives from live data
        if picked and best and picked != best:
            best_odds = {"Home": home_o, "Draw": draw_o, "Away": away_o}.get(best, 0)
            alternatives.insert(0, f"Swap to {labels[best]} @ {best_odds} ({best_prob}% probability)")

        # Double chance alternatives for risky straight picks
        if picked in ("Home", "Away"):
            if picked == "Home" and home_o > 0 and draw_o > 0:
                dc_odds = round(1 / (1/home_o + 1/draw_o), 2)
                alternatives.append(f"1X Double Chance @ {dc_odds} (covers draw too)")
            elif picked == "Away" and away_o > 0 and draw_o > 0:
                dc_odds = round(1 / (1/away_o + 1/draw_o), 2)
                alternatives.append(f"X2 Double Chance @ {dc_odds} (covers draw too)")

    else:
        # No live data — odds-only verdict
        if odds > 4.0:
            verdict = "REMOVE"
            verdict_reason = f"Odds {odds} imply only {user_prob}% chance - too risky for acca"
            risk_score += 2
        elif odds > 3.0:
            verdict = "SWAP"
            verdict_reason = f"Odds {odds} = {user_prob}% implied - consider safer pick"
        elif odds > 2.0:
            verdict = "KEEP"
            verdict_reason = f"Odds {odds} = {user_prob}% implied - reasonable risk"
        else:
            verdict = "KEEP"
            verdict_reason = f"Low odds ({odds}) = {user_prob}% - solid probability"

    # Final risk level
    if risk_score >= 5:
        risk_level = "RISKY"
    elif risk_score >= 3:
        risk_level = "MODERATE"
    elif risk_score >= 1:
        risk_level = "LOW"
    else:
        risk_level = "SAFE"

    return {
        **pick,
        "verdict": verdict,
        "verdict_reason": verdict_reason,
        "risk_flags": risk_flags,
        "risk_level": risk_level,
        "risk_score": risk_score,
        "user_prob": user_prob,
        "alternatives": alternatives,
        "live_data": live_data,
    }


def analyze_accumulator(assessed_picks: list[dict]) -> dict:
    """Analyze the full accumulator: combined probability and risk."""
    total_picks = len(assessed_picks)

    # Combined probability (all picks must win)
    combined_prob = 1.0
    combined_odds = 1.0
    for p in assessed_picks:
        prob = p["user_prob"] / 100.0
        if prob <= 0:
            prob = 1.0 / p["odds"] if p["odds"] > 1 else 0.1
        combined_prob *= prob
        combined_odds *= p["odds"]

    combined_prob_pct = round(combined_prob * 100, 2)
    combined_odds = round(combined_odds, 1)

    # Expected value (simplified)
    ev = round(combined_prob * combined_odds * 100, 1)  # per 100 staked

    # Risk assessment
    risky_count = sum(1 for p in assessed_picks if p["verdict"] == "REMOVE")
    swap_count = sum(1 for p in assessed_picks if p["verdict"] == "SWAP")
    keep_count = sum(1 for p in assessed_picks if p["verdict"] == "KEEP")

    # Recommendation
    if risky_count > 0:
        acca_verdict = "HIGH RISK"
        acca_reason = f"{risky_count} pick(s) should be removed, {swap_count} should be swapped"
    elif swap_count > total_picks // 2:
        acca_verdict = "RISKY"
        acca_reason = f"More than half your picks ({swap_count}/{total_picks}) disagree with the market"
    elif total_picks > 5:
        acca_verdict = "RISKY"
        acca_reason = f"{total_picks} picks is too many - each extra pick multiplies your losing chance"
    elif swap_count > 0:
        acca_verdict = "MODERATE"
        acca_reason = f"{swap_count} pick(s) could be improved, {keep_count} look solid"
    else:
        acca_verdict = "REASONABLE"
        acca_reason = f"All {keep_count} picks look solid"

    return {
        "total_picks": total_picks,
        "combined_odds": combined_odds,
        "combined_prob_pct": combined_prob_pct,
        "ev_per_100": ev,
        "risky_count": risky_count,
        "swap_count": swap_count,
        "keep_count": keep_count,
        "acca_verdict": acca_verdict,
        "acca_reason": acca_reason,
    }


# =============================================================================
# LIVE ANALYSIS — Match user games to SportyBet API and build 3 slips
# =============================================================================


def _extract_potential_teams(raw_text: str) -> list[str]:
    """Extract potential team names from OCR text.

    Looks for lines that could be football team names — alphabetic text
    that isn't a known UI label, bet type, or noise.
    """
    import re
    lines = raw_text.strip().split("\n")
    teams = []
    skip_exact = {
        "home", "draw", "away", "over", "under", "btts", "yes", "no",
        "gg", "ng", "double", "chance", "dnb", "win", "goals", "total",
        "odds", "stake", "payout", "bonus", "max", "boost", "live",
        "popular", "today", "upcoming", "football", "soccer", "slip",
        "bet", "ticket", "acca", "accumulator", "potential", "returns",
        "1x2", "ht", "ft", "match", "game", "fixture", "selection",
        "vs", "v", "and", "or", "the", "of", "fc", "sc",
    }
    skip_contains = [
        "betslip", "booking", "code", "example", "selections",
        "stake", "payout", "sportybet", "nigeria", "di niseria",
        "max bonus", "odds boost", "booking code",
    ]
    for line in lines:
        line = line.strip()
        if not line or len(line) < 2:
            continue
        # Remove leading/trailing noise chars
        cleaned = re.sub(r"^[@\d.)\s\-\|,;:]+", "", line).strip()
        cleaned = re.sub(r"[@:\d.\s\-\|,;:]+$", "", cleaned).strip()
        if not cleaned or len(cleaned) < 2:
            continue
        # Must contain letters
        alpha_count = sum(1 for c in cleaned if c.isalpha())
        if alpha_count < 2:
            continue
        # Skip exact matches with known labels
        if cleaned.lower().strip() in skip_exact:
            continue
        # Skip lines containing known UI words
        lower = cleaned.lower()
        if any(sw in lower for sw in skip_contains):
            continue
        # Skip if it starts with a known bet type prefix
        lower = cleaned.lower()
        if any(lower.startswith(p) for p in [
            "over ", "under ", "btts ", "double chance", "draw no bet",
            "home ", "away ", "both teams", "total goals",
        ]):
            continue
        teams.append(cleaned)
    return teams


def _match_teams_to_events(
    team_names: list[str],
    events: list[dict],
) -> dict[str, dict]:
    """Match individual team names against SportyBet events.

    Returns {event_key: event_dict} for matched events.
    Tries multiple strategies:
    1. Match individual team names against home/away of each event
    2. Try pairing extracted teams and match as (teamA, teamB) pairs
    """
    matched = {}
    used_events = set()

    # Strategy 1: Match individual teams (one name matches home or away)
    for team in team_names:
        n = normalize_name(team)
        if len(n) < 3:
            continue
        best_event = None
        best_score = 0.0

        for event in events:
            eid = event.get("event_id", "")
            if eid in used_events:
                continue
            eh = normalize_name(event["home"])
            ea = normalize_name(event["away"])

            # Check if this team matches either home or away
            score_home = _word_similarity(n, eh)
            score_away = _word_similarity(n, ea)
            score = max(score_home, score_away)

            # Also check substring containment (for OCR partial names)
            if n in eh or eh in n:
                score = max(score, 0.6)
            if n in ea or ea in n:
                score = max(score, 0.6)

            if score > best_score:
                best_score = score
                best_event = event

        if best_event and best_score >= 0.5:
            eid = best_event.get("event_id", "")
            if eid not in used_events:
                key = f"{best_event['home']} vs {best_event['away']}"
                matched[key] = best_event
                used_events.add(eid)
                logger.info(f"Matched team '{team}' -> {key} (score: {best_score:.2f})")

    # Strategy 2: If fewer than 2 matches, try pairing teams
    if len(matched) < 2 and len(team_names) >= 2:
        # Try all possible pairs of extracted team names
        for i in range(len(team_names)):
            if len(matched) >= 2:
                break
            for j in range(i + 1, len(team_names)):
                if len(matched) >= 2:
                    break
                t1, t2 = team_names[i], team_names[j]
                # Skip if either team already matched
                already_matched = False
                for ev in matched.values():
                    if (normalize_name(t1) in normalize_name(ev["home"]) or
                        normalize_name(t1) in normalize_name(ev["away"]) or
                        normalize_name(t2) in normalize_name(ev["home"]) or
                        normalize_name(t2) in normalize_name(ev["away"])):
                        already_matched = True
                        break
                if already_matched:
                    continue
                # Try to find this pair in events
                for event in events:
                    eid = event.get("event_id", "")
                    if eid in used_events:
                        continue
                    eh = normalize_name(event["home"])
                    ea = normalize_name(event["away"])
                    n1 = normalize_name(t1)
                    n2 = normalize_name(t2)

                    fwd = _word_similarity(n1, eh) + _word_similarity(n2, ea)
                    rev = _word_similarity(n1, ea) + _word_similarity(n2, eh)
                    score = max(fwd, rev)

                    if score >= 0.5:
                        key = f"{event['home']} vs {event['away']}"
                        matched[key] = event
                        used_events.add(eid)
                        logger.info(f"Pair matched: {t1} + {t2} -> {key} (score: {score:.2f})")
                        break

    return matched


async def _analyze_with_live_data(raw_text: str) -> str:
    """Full pipeline: extract games → fetch SportyBet events → match → analyze → build slips.

    1. Parse team names from user input (tries multiple strategies)
    2. Fetch live SportyBet events (cached)
    3. Match each game to a SportyBet event
    4. Run analyze_all_markets_full on matched events
    5. Build 3 slips from the per-match plays
    6. Return formatted message
    """
    # Strategy 1: Extract "Team vs Team" pairs
    match_names = get_match_names(raw_text)
    logger.info(f"Strategy 1 - extracted {len(match_names)} match pairs: {match_names}")

    # Strategy 2: If no pairs found, extract individual team names
    if not match_names:
        potential_teams = _extract_potential_teams(raw_text)
        logger.info(f"Strategy 2 - extracted {len(potential_teams)} potential teams: {potential_teams}")

        if not potential_teams:
            # Nothing useful in OCR — show the user what was extracted
            return (
                f"\u274c Could not identify any team names from the image.\n\n"
                f"Extracted text:\n```\n{raw_text[:500]}\n```\n\n"
                f"Try sending the slip as text instead:\n"
                f"```\nTeam A vs Team B\nTeam C vs Team D\n```"
            )

        # Fetch live events from SportyBet
        events = await fetch_live_events()
        logger.info(f"Fetched {len(events)} SportyBet events")

        if not events:
            return (
                f"\u274c Could not fetch live SportyBet events.\n\n"
                f"Extracted teams: {', '.join(potential_teams[:8])}\n"
                f"Please try again in a moment."
            )

        # Match individual teams to events
        matched_events = _match_teams_to_events(potential_teams, events)

        if not matched_events:
            return (
                f"\u274c Could not match any teams to live SportyBet events.\n\n"
                f"Extracted: {', '.join(potential_teams[:8])}\n"
                f"Try sending the slip as text with clear team names."
            )

        # Analyze matched events
        match_plays = {}
        for display_name, event in matched_events.items():
            analysis = analyze_all_markets_full(event)
            plays = analysis.get("plays", [])
            if plays:
                match_plays[display_name] = plays

        if not match_plays:
            return (
                "\u26a0\ufe0f Matched events but no market data available.\n"
                "The matches may not have odds open yet."
            )

        result = analyze_slip_with_events(match_plays)
        return result

    # We have "Team vs Team" pairs — standard flow
    events = await fetch_live_events()
    logger.info(f"Fetched {len(events)} SportyBet events")

    if not events:
        return analyze_slip_v2(raw_text)

    match_plays = {}
    unmatched = []

    for team1, team2 in match_names:
        event = find_matching_event(team1, team2, events)
        if event:
            display_name = f"{event['home']} vs {event['away']}"
            analysis = analyze_all_markets_full(event)
            plays = analysis.get("plays", [])
            if plays:
                match_plays[display_name] = plays
                logger.info(f"Matched: {team1} vs {team2} -> {display_name} ({len(plays)} plays)")
            else:
                unmatched.append(f"{team1} vs {team2}")
        else:
            unmatched.append(f"{team1} vs {team2}")
            logger.info(f"No match found: {team1} vs {team2}")

    if not match_plays:
        logger.info("No events matched, falling back to static analysis")
        return analyze_slip_v2(raw_text)

    result = analyze_slip_with_events(match_plays)

    if unmatched:
        result += f"\n\u26a0\ufe0f Could not find live odds for: {', '.join(unmatched[:3])}"

    return result


# =============================================================================
# BOT COMMAND HANDLERS
# =============================================================================


async def _safe_edit(msg, text):
    """Edit a message, ignoring 'Message is not modified' errors."""
    try:
        await msg.edit_text(text)
    except BadRequest as e:
        if "Message is not modified" not in str(e):
            raise


async def _ensure_private(update: Update) -> bool:
    """Return True if the message is from a private chat."""
    if update.effective_chat and update.effective_chat.type != "private":
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start."""
    if not await _ensure_private(update):
        return
    user = update.effective_user
    username = user.first_name or "there"
    welcome = (
        f"Welcome to SportyBot Free, {username}!\n\n"
        f"I analyze your betting slips using live SportyBet data\n"
        f"and flag risky picks so you can bet smarter.\n\n"
        f"How it works:\n"
        f"1. Send me a screenshot of your betting slip\n"
        f"2. I extract text via OCR\n"
        f"3. I fetch live odds from SportyBet\n"
        f"4. I compare your picks against the market\n"
        f"5. I flag risky picks and suggest safer alternatives\n\n"
        f"Just upload a photo of your slip to get started!\n\n"
        f"Type /help for more details."
    )
    await update.message.reply_text(welcome)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help."""
    if not await _ensure_private(update):
        return
    help_text = (
        "How to Use SportyBot Free\n\n"
        "Commands:\n"
        "/start - Welcome message\n"
        "/analyze - Analyze a betting slip from text\n"
        "/help - This help message\n\n"
        "Sending a Betting Slip:\n"
        "1. Type /analyze and paste your picks\n"
        "2. Or take a screenshot and send it as a photo\n"
        "3. Wait a few seconds for analysis\n\n"
        "What I Analyze:\n"
        "- Detect your strategy (safe/moderate/risky)\n"
        "- Score risk per pick (LOW/MEDIUM/HIGH/EXTREME)\n"
        "- Decide KEEP, SWAP, or REMOVE for each pick\n"
        "- Generate safer alternatives\n"
        "- Build an optimized slip with better win probability\n\n"
        "Want better picks?\n"
        "Upgrade to VIP for AI-optimized daily picks.\n"
        "DM the admin to verify your payment and get access."
    )
    await update.message.reply_text(help_text)


async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /analyze — analyze a betting slip from text with live SportyBet data."""
    if not await _ensure_private(update):
        return

    raw_text = " ".join(context.args) if context.args else ""

    if not raw_text:
        await update.message.reply_text(
            "\U0001f4cb *Slip Analyzer*\n\n"
            "Paste your betting slip and I'll build 3 optimized slips:\n\n"
            "*Usage:* `/analyze your slip here`\n\n"
            "*Example:*\n"
            "`Man City vs Arsenal\n"
            "Liverpool vs Chelsea\n"
            "Barcelona vs Real Madrid`\n\n"
            "Or send your picks as a message, or a *screenshot* of your slip!\n\n"
            "I'll fetch live SportyBet odds for your games and find the best markets.",
            parse_mode="Markdown",
        )
        context.user_data["awaiting_analyze"] = True
        return

    progress = await update.message.reply_text("\u23f3 Fetching live odds for your games...")

    try:
        result = await _analyze_with_live_data(raw_text)
        await progress.delete()
        await update.message.reply_text(result)
    except Exception as e:
        logger.error(f"Error analyzing slip: {e}", exc_info=True)
        await progress.delete()
        await update.message.reply_text(f"\u274c Error analyzing slip: {str(e)}")


async def handle_analyze_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages — check for slip patterns or /analyze flow."""
    text = update.message.text or ""
    import re

    # Check if text looks like a slip submission (contains "vs" pattern)
    vs_count = len(re.findall(r'\bvs?\.?\b', text, re.IGNORECASE))

    if vs_count >= 1 and len(text) > 10:
        # Route to pool slip scanner
        handled = await handle_pool_slip_text(update, context)
        if handled:
            return

    # Original /analyze flow
    if not context.user_data.get("awaiting_analyze"):
        return

    context.user_data["awaiting_analyze"] = False
    raw_text = update.message.text or ""

    if not raw_text.strip():
        await update.message.reply_text("\u274c No text detected. Try again with /analyze")
        return

    progress = await update.message.reply_text("\u23f3 Fetching live odds for your games...")

    try:
        result = await _analyze_with_live_data(raw_text)
        await progress.delete()
        await update.message.reply_text(result)
    except Exception as e:
        logger.error(f"Error analyzing text: {e}", exc_info=True)
        await progress.delete()
        await update.message.reply_text(f"\u274c Error analyzing slip: {str(e)}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo uploads — OCR → match teams against SportyBet → build 3 slips."""
    if not await _ensure_private(update):
        return

    # Check if in search mode
    if context.user_data.get("search_mode"):
        context.user_data["search_mode"] = False
        await handle_search_photo(update, context)
        return

    context.user_data["awaiting_analyze"] = False
    progress_msg = await update.message.reply_text("\u23f3 Reading your slip...")

    # Download the photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

    try:
        # OCR
        await _safe_edit(progress_msg, "\u23f3 Extracting text from image...")
        extracted_text = extract_text_from_image(tmp_path)

        if not extracted_text.strip():
            await _safe_edit(progress_msg,
                "\u274c Could not extract any text from the image.\n"
                "Try sending the slip as text instead:\n"
                "`Man City vs Arsenal\nLiverpool vs Chelsea`"
            )
            return

        logger.info(f"OCR raw text:\n{extracted_text}")

        # Extract all potential team names from the OCR
        potential_teams = _extract_potential_teams(extracted_text)
        logger.info(f"Potential teams from OCR: {potential_teams}")

        # Also try "Team vs Team" patterns
        match_pairs = get_match_names(extracted_text)
        logger.info(f"Team pairs from OCR: {match_pairs}")

        if not potential_teams and not match_pairs:
            # Show user what OCR found
            clean_text = extracted_text.strip()[:300]
            await _safe_edit(progress_msg,
                f"\u274c Could not find team names in the image.\n\n"
                f"OCR text:\n```\n{clean_text}\n```\n\n"
                f"Try sending your picks as text:\n"
                f"`Man City vs Arsenal\nLiverpool vs Chelsea`"
            )
            return

        # --- NEW VIP PREDICTION POOL CHECK ---
        from core.slip_matcher import match_against_pool
        from core.pool_slip_generator import generate_slips_from_matches, format_slip_telegram
        from core.pool_manager import get_pool_summary

        pool_handled = False
        summary = get_pool_summary()
        
        # If the pool is populated and we extracted pairs, check pool first
        if summary.get("active_matches", 0) > 0 and len(match_pairs) >= 1:
            await _safe_edit(progress_msg, "\u23f3 Analyzing against VIP Prediction Pool...")
            parsed = [{"home": t1, "away": t2, "raw_line": f"{t1} vs {t2}"} for t1, t2 in match_pairs]
            match_result = match_against_pool(parsed)
            matched = match_result["matched"]
            unmatched = match_result["unmatched"]
            
            # Use pool if we matched at least 2 games
            if len(matched) >= 2:
                slips = generate_slips_from_matches(matched)
                
                msg_parts = []
                if unmatched:
                    msg_parts.append("\u26a0\ufe0f Some matches fell back to live odds or were not in VIP pool:")
                    for u in unmatched:
                        msg_parts.append(f"  - {u['slip_match']['raw_line']}")
                    msg_parts.append("")
                
                safe_msg = format_slip_telegram(slips["safe_slip"], "SAFE", "LOW RISK")
                medium_msg = format_slip_telegram(slips["medium_slip"], "MEDIUM", "MEDIUM RISK")
                risky_msg = format_slip_telegram(slips["risky_slip"], "RISKY", "HIGH RISK")
                
                full_msg = "\n".join(msg_parts) if msg_parts else ""
                await progress_msg.delete()
                
                if full_msg:
                    await update.message.reply_text(full_msg[:4000])
                    
                for slip_msg in [safe_msg, medium_msg, risky_msg]:
                    if slip_msg and "No qualifying" not in slip_msg:
                        await update.message.reply_text(slip_msg[:4000])
                
                pool_handled = True
                
        if pool_handled:
            return
        # ------------------------------------

        # Fetch SportyBet events (Fallback)
        await _safe_edit(progress_msg, "\u23f3 Fetching live SportyBet odds (VIP fallback)...")
        events = await fetch_live_events()
        logger.info(f"Fetched {len(events)} SportyBet events")

        if not events:
            await _safe_edit(progress_msg,
                "\u274c Could not fetch live odds. Please try again."
            )
            return

        # Match strategy: try team pairs first, then individual teams
        match_plays = {}

        # Strategy 1: Match "Team vs Team" pairs directly
        for team1, team2 in match_pairs:
            event = find_matching_event(team1, team2, events)
            if event:
                display_name = f"{event['home']} vs {event['away']}"
                analysis = analyze_all_markets_full(event)
                plays = analysis.get("plays", [])
                if plays:
                    match_plays[display_name] = plays
                    logger.info(f"Pair matched: {team1} vs {team2} -> {display_name}")

        # Strategy 2: If no pairs matched, try individual team names
        if not match_plays and potential_teams:
            matched_events = _match_teams_to_events(potential_teams, events)
            for display_name, event in matched_events.items():
                analysis = analyze_all_markets_full(event)
                plays = analysis.get("plays", [])
            if plays:
                match_plays[display_name] = plays

        if not match_plays:
            team_list = [t for t, _ in match_pairs] if match_pairs else potential_teams[:8]
            await _safe_edit(progress_msg,
                f"\u274c Could not match teams to live events.\n\n"
                f"Extracted: {', '.join(team_list)}\n\n"
                f"These matches may not be available on SportyBet.\n"
                f"Try matches that are currently available."
            )
            return

        # Check if we have enough matches
        if len(match_plays) < 2:
            matched = list(match_plays.keys())[0] if match_plays else "Unknown"
            await _safe_edit(progress_msg,
                f"\u26a0\ufe0f Only 1 match found: {matched}\n\n"
                f"I need at least 2 matches to build slip combinations.\n\n"
                f"Your slip teams: {', '.join([f'{t1} vs {t2}' for t1, t2 in match_pairs])}\n\n"
                f"These matches may have already started or are not on SportyBet."
            )
            return

        # Use enhanced analyzer with search and tier classification
        match_info = {}
        for display_name in match_plays.keys():
            # Try to get league from events
            for event in events:
                ev_name = f"{event.get('home', '')} vs {event.get('away', '')}"
                if ev_name == display_name:
                    match_info[display_name] = {
                        "home": event.get("home", ""),
                        "away": event.get("away", ""),
                        "league": event.get("league", "")
                    }
                    break

        # Progress callback for search
        search_progress_shown = []
        def progress_callback(current, total, match_key):
            if match_key not in search_progress_shown:
                search_progress_shown.append(match_key)
                # Update progress message (will be done synchronously)

        # Run enhanced analysis
        result, analysis_id = analyze_slip_enhanced(
            match_plays=match_plays,
            match_info=match_info,
            use_search=True,
            progress_callback=progress_callback
        )

        # Store analysis_id in context for /full command
        if analysis_id:
            context.user_data["last_analysis_id"] = analysis_id

        await progress_msg.delete()
        await update.message.reply_text(result, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error processing photo: {e}", exc_info=True)
        await _safe_edit(progress_msg,
            "An error occurred while processing your slip. Please try again."
        )
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# =============================================================================
# POOL SLIP SCANNER
# =============================================================================


async def cmd_pool(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /pool — show current prediction pool summary."""
    try:
        from core.pool_manager import get_pool_summary, get_top_predictions

        summary = get_pool_summary()
        top = get_top_predictions(min_confidence=80, max_results=5)

        msg = [
            "PREDICTION POOL",
            "=" * 24,
            f"Active matches: {summary['active_matches']}",
            f"Total predictions: {summary['total_predictions']}",
            f"Today's matches: {summary['today_matches']}",
            f"Avg confidence: {summary['avg_confidence']}",
            f"Overall accuracy: {summary['overall_accuracy']}%",
            "",
        ]

        if top:
            msg.append("TOP PICKS:")
            for i, p in enumerate(top[:5], 1):
                msg.append(f"  {i}. {p['home_team']} vs {p['away_team']}")
                msg.append(f"     {p['market']}: {p['pick']} @ {p['odds']:.2f}")
                msg.append(f"     Confidence: {p['confidence']:.0f} | {p['risk_tier']}")
                msg.append("")

        msg.append("Send your slip (text or photo) to get optimized picks!")

        await update.message.reply_text("\n".join(msg))

    except Exception as e:
        logger.error(f"Pool command error: {e}")
        await update.message.reply_text("Pool data unavailable. Run /scan first.")


async def cmd_scan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /scan — trigger weekly pool population."""
    progress = await update.message.reply_text("Scanning matches and populating prediction pool...")

    try:
        from core.weekly_runner import run_weekly_cycle
        result = run_weekly_cycle()

        await progress.edit_text(
            f"Pool populated!\n\n"
            f"Events scraped: {result.get('events', 0)}\n"
            f"Qualified matches: {result.get('qualified', 0)}\n"
            f"Predictions stored: {result.get('predictions_stored', 0)}\n"
            f"Time: {result.get('duration', 0)}s\n\n"
            f"Send your slip to get optimized picks!"
        )

    except Exception as e:
        logger.error(f"Scan error: {e}")
        await progress.edit_text(f"Scan failed: {e}")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search — use DuckDuckGo search-based slip analysis."""
    if not await _ensure_private(update):
        return

    await update.message.reply_text(
        "🔍 *Search-Based Analysis*\n\n"
        "Send me your betting slip as text or photo.\n"
        "I'll search for real form data for each match!\n\n"
        "Example:\n"
        "`Arsenal vs Chelsea @1.85`\n"
        "`Man City vs Liverpool @2.10`",
        parse_mode="Markdown"
    )
    context.user_data["search_mode"] = True


async def cmd_full(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /full_<id> — show detailed analysis."""
    if not await _ensure_private(update):
        return

    # Get analysis ID from command args or last analysis
    args = context.args if context.args else []
    
    if args:
        analysis_id = args[0].strip()
    else:
        # Use last analysis ID
        analysis_id = context.user_data.get("last_analysis_id")
    
    if not analysis_id:
        await update.message.reply_text(
            "\u274c No analysis found.\n\n"
            "Send a slip photo first, then use /full to see detailed analysis."
        )
        return
    
    # Get full analysis
    full_result = get_full_analysis(analysis_id)
    
    if "not found" in full_result.lower():
        await update.message.reply_text(full_result)
        return
    
    # Send as multiple messages if too long
    if len(full_result) > 3500:
        # Split into chunks
        chunks = []
        current = ""
        for line in full_result.split("\n"):
            if len(current) + len(line) + 1 > 3500:
                chunks.append(current)
                current = line + "\n"
            else:
                current += line + "\n"
        if current:
            chunks.append(current)
        
        for i, chunk in enumerate(chunks):
            if i == 0:
                await update.message.reply_text(f"\U0001f4d6 Full Analysis (Part {i+1}/{len(chunks)})\n\n{chunk}")
            else:
                await update.message.reply_text(f"Part {i+1}/{len(chunks)}\n\n{chunk}")
    else:
        await update.message.reply_text(f"\U0001f4d6 Full Analysis\n\n{full_result}")


async def handle_search_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle photo in search mode — OCR → search each match → analyze."""
    if not await _ensure_private(update):
        return

    progress_msg = await update.message.reply_text("🔍 Reading your slip...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

    try:
        await _safe_edit(progress_msg, "🔍 Extracting text from image...")
        extracted_text = extract_text_from_image(tmp_path)

        if not extracted_text.strip():
            await _safe_edit(progress_msg,
                "❌ Could not extract any text from the image.\n"
                "Try sending the slip as text."
            )
            return

        logger.info(f"Search mode OCR: {extracted_text[:200]}")

        await _safe_edit(progress_msg, "🔍 Searching for match data (this may take a minute)...")

        # Run search-based analysis
        result = analyze_slip_with_search(extracted_text)

        await progress_msg.delete()
        await update.message.reply_text(result, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Search analysis error: {e}", exc_info=True)
        await _safe_edit(progress_msg, f"❌ Error analyzing slip: {str(e)}")
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def handle_pool_slip_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text that looks like a slip submission (team vs team patterns)."""
    text = update.message.text or ""
    import re

    # Check if text contains "vs" or "v" patterns (slip submission)
    vs_count = len(re.findall(r'\bvs?\.?\b', text, re.IGNORECASE))

    if vs_count >= 1 and len(text) > 10:
        # This looks like a slip submission
        progress = await update.message.reply_text("Analyzing your slip against the prediction pool...")

        try:
            from core.slip_matcher import parse_slip_text, match_against_pool
            from core.pool_slip_generator import generate_slips_from_matches, format_slip_telegram
            from core.pool_manager import log_user_slip, get_pool_summary

            # Parse the slip
            parsed = parse_slip_text(text)

            if not parsed:
                await progress.edit_text("Could not parse any matches from your text. Try format: 'Team A vs Team B'")
                return

            # Check if pool has data
            summary = get_pool_summary()
            if summary["active_matches"] == 0:
                await progress.edit_text(
                    "Prediction pool is empty. An admin needs to run /scan first.\n"
                    "Try again later or use /pool to check status."
                )
                return

            # Match against pool
            match_result = match_against_pool(parsed)
            matched = match_result["matched"]
            unmatched = match_result["unmatched"]

            if not matched:
                msg = "No matches found in the prediction pool.\n\n"
                for u in unmatched:
                    msg += f"  - {u['slip_match']['home']} vs {u['slip_match']['away']}: {u['reason']}\n"
                msg += "\nUse /pool to see available matches."
                await progress.edit_text(msg)
                return

            # Generate 3 slips
            slips = generate_slips_from_matches(matched)

            # Format and send
            msg_parts = []
            if unmatched:
                msg_parts.append("Some matches not in pool:")
                for u in unmatched:
                    msg_parts.append(f"  - {u['slip_match']['raw_line']}")
                msg_parts.append("")

            safe_msg = format_slip_telegram(slips["safe_slip"], "SAFE", "LOW RISK")
            medium_msg = format_slip_telegram(slips["medium_slip"], "MEDIUM", "MEDIUM RISK")
            risky_msg = format_slip_telegram(slips["risky_slip"], "RISKY", "HIGH RISK")

            # Send in parts (Telegram 4096 char limit)
            full_msg = "\n".join(msg_parts) if msg_parts else ""

            await progress.delete()

            if full_msg:
                await update.message.reply_text(full_msg[:4000])

            for slip_msg in [safe_msg, medium_msg, risky_msg]:
                if slip_msg and "No qualifying" not in slip_msg:
                    await update.message.reply_text(slip_msg[:4000])

            # Log interaction
            try:
                log_user_slip(
                    user_id=update.effective_user.id,
                    username=update.effective_user.username or "",
                    slip_text=text,
                    parsed_matches=[m["slip_match"] for m in matched],
                    returned_slips={
                        "safe_count": len(slips["safe_slip"]),
                        "medium_count": len(slips["medium_slip"]),
                        "risky_count": len(slips["risky_slip"]),
                    },
                )
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Slip scan error: {e}", exc_info=True)
            await progress.edit_text(f"Error analyzing slip: {e}")

        return True  # Indicates we handled it

    return False  # Not a slip, let other handlers process


# =============================================================================
# ERROR HANDLER
# =============================================================================


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log unhandled exceptions."""
    logger.error(f"Exception: {context.error}", exc_info=context.error)
    if isinstance(update, Update):
        msg = update.effective_message
        if msg:
            await msg.reply_text("Something went wrong. Please try again later.")


# =============================================================================
# MAIN
# =============================================================================


def main() -> None:
    """Initialize and start the free bot."""
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("pool", cmd_pool))
    app.add_handler(CommandHandler("scan", cmd_scan))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("full", cmd_full))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_analyze_text))
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))
    app.add_error_handler(error_handler)

    # Cleanup old analyses periodically
    cleanup_old_analyses(max_age_hours=24)

    logger.info("SportyBot Free is starting...")
    print("SportyBot Free is running. Press Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
