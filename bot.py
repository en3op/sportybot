"""
SportyBot - VIP Telegram Betting Picks Bot
==========================================
Private 1-on-1 bot for paying users.
Fetches daily football matches from API-Football and provides
data-driven betting picks with confidence ratings.

Usage:
    pip install -r requirements.txt
    python bot.py
"""

import os
import re
import sqlite3
import logging
import tempfile
import asyncio
from datetime import datetime, timedelta

import requests
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
from sportybet_scraper import generate_daily_picks, analyze_all_markets, fetch_upcoming_events
from elite_engine import (
    extract_team_metrics, analyze_match_edge,
    format_edge_message, MatchEdge,
)

# =============================================================================
# CONFIGURATION - Replace these placeholders with your actual values
# =============================================================================

BOT_TOKEN = os.environ.get("VIP_BOT_TOKEN", "8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk")

# Direct API-Football credentials (api-football.com / api-sports.io)
API_FOOTBALL_KEY = os.environ.get("API_FOOTBALL_KEY", "932929ad49d522381384d69aec31fc99")
API_FOOTBALL_BASE_URL = "https://v3.football.api-sports.io"

# Paystack payment link for VIP subscription
PAYSTACK_LINK = "https://paystack.com/pay/YOUR_PAYMENT_LINK_HERE"

# Admin user IDs (Telegram user IDs who can manage VIP users)
ADMIN_USER_IDS = [6670391476]  # @sportybot_admin

# Current season for API-Football queries
CURRENT_SEASON = 2025

# Target leagues: (league_id, league_name)
TARGET_LEAGUES = {
    39: "Premier League",
    140: "La Liga",
    135: "Serie A",
    78: "Bundesliga",
    61: "Ligue 1",
    2: "Champions League",
    3: "Europa League",
    848: "Conference League",
    345: "Copa Libertadores",
    346: "Copa Sudamericana",
    169: "Super Lig",
    203: "Super Lig (Turkey)",
    88: "Eredivisie",
    94: "Primeira Liga",
    179: "Premiership (Scotland)",
    188: "Pro League (Belgium)",
    144: "Jupiler Pro League",
    218: "Bundesliga (Austria)",
    119: "Superliga (Denmark)",
    204: "Eliteserien (Norway)",
    113: "Allsvenskan (Sweden)",
    239: "Liga MX",
    253: "MLS",
    128: "Primera Division (Argentina)",
    71: "Serie A (Brazil)",
    164: "OBOS-ligaen",
    262: "Liga MX Expansion",
    307: "Saudi Pro League",
    1060: "A-League",
    292: "K League 1",
    298: "J1 League",
    5: "Nations League",
    10: "Friendlies",
    15: "FIFA Club World Cup",
}

def _is_popular_league(league_name: str) -> bool:
    """Check if a league is worth analyzing (exclude youth/reserve/women's)."""
    name_lower = league_name.lower()
    # Skip youth, reserve, women's, U19, U20, U21, U23 leagues
    skip_keywords = ["u19", "u20", "u21", "u23", "women", "female", "frauen",
                     "damall", "femenina", "reserve", "junior", "kwindeliga"]
    if any(kw in name_lower for kw in skip_keywords):
        return False
    return True

# VIP subscription duration in days
VIP_DURATION_DAYS = 7  # 1 week

# Database file path
DB_PATH = "vip_users.db"

# Tesseract OCR executable path (update if installed in a non-standard location)
# Leave as None to use system PATH
TESSERACT_CMD = None  # e.g., r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# =============================================================================
# LOGGING
# =============================================================================

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# =============================================================================
# DATABASE LAYER (SQLite)
# =============================================================================


def init_db() -> None:
    """Create the VIP users table if it does not exist."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id    INTEGER PRIMARY KEY,
            username   TEXT,
            added_date TEXT,
            expiry_date TEXT
        )
        """
    )
    conn.commit()
    conn.close()
    logger.info("Database initialized.")


def is_vip(user_id: int) -> bool:
    """Check if a user has an active (non-expired) VIP subscription."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT expiry_date FROM vip_users WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return False
    expiry = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
    return datetime.now() < expiry


def add_vip(user_id: int, username: str, weeks: int = 1) -> str:
    """Add or extend a VIP subscription. Returns the new expiry date string."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    now = datetime.now()

    # Check if user already exists and extend from current expiry if still active
    cursor.execute(
        "SELECT expiry_date FROM vip_users WHERE user_id = ?", (user_id,)
    )
    row = cursor.fetchone()
    if row:
        current_expiry = datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S")
        base = max(now, current_expiry)
    else:
        base = now

    new_expiry = base + timedelta(weeks=weeks)
    expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
    added_str = now.strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        INSERT OR REPLACE INTO vip_users (user_id, username, added_date, expiry_date)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, username or "unknown", added_str, expiry_str),
    )
    conn.commit()
    conn.close()
    return expiry_str


def remove_vip(user_id: int) -> bool:
    """Remove a VIP user. Returns True if a row was deleted."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM vip_users WHERE user_id = ?", (user_id,))
    deleted = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def get_vip_info(user_id: int) -> dict | None:
    """Return VIP info dict for a user, or None if not in database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT username, added_date, expiry_date FROM vip_users WHERE user_id = ?",
        (user_id,),
    )
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "username": row[0],
        "added_date": row[1],
        "expiry_date": row[2],
    }


def list_all_vips() -> list[dict]:
    """Return all VIP users from the database."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, added_date, expiry_date FROM vip_users")
    rows = cursor.fetchall()
    conn.close()
    now = datetime.now()
    results = []
    for row in rows:
        expiry = datetime.strptime(row[3], "%Y-%m-%d %H:%M:%S")
        results.append({
            "user_id": row[0],
            "username": row[1],
            "added_date": row[2],
            "expiry_date": row[3],
            "active": now < expiry,
        })
    return results


# =============================================================================
# OCR FUNCTIONS
# =============================================================================

def extract_text_from_image(image_path: str) -> str:
    """Extract text from image using Tesseract OCR."""
    tesseract_path = TESSERACT_CMD
    if tesseract_path and os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
    elif os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe"):
        pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

    try:
        img = Image.open(image_path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        text = pytesseract.image_to_string(img, config='--psm 4')
        return text.strip()
    except Exception as e:
        logger.error(f"OCR failed: {e}")
        return ""


def parse_slip_text(text: str) -> list[dict]:
    """Parse extracted OCR text into structured picks."""
    picks = []
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        
        # Try to extract team vs team pattern
        vs_match = re.search(r'([A-Za-z][A-Za-z\s\.]+?)\s+(?:vs?\.?|v|-)\s+([A-Za-z][A-Za-z\s\.]+)', line, re.IGNORECASE)
        if vs_match:
            team1 = vs_match.group(1).strip()
            team2 = vs_match.group(2).strip()
            
            # Try to extract odds
            odds_match = re.search(r'(\d+\.\d{1,2})', line)
            odds = float(odds_match.group(1)) if odds_match else 1.85
            
            # Infer bet type from odds
            if odds < 1.5:
                bet_type = "Home Win"
            elif odds > 3.0:
                bet_type = "Away Win"
            else:
                bet_type = "Draw/Home"
            
            picks.append({
                "team1": team1,
                "team2": team2,
                "bet_type": bet_type,
                "odds": odds,
            })
    
    return picks


# =============================================================================
# API-FOOTBALL INTEGRATION
# =============================================================================

_api_semaphore = asyncio.Semaphore(1)  # Rate-limit to 1 concurrent request


def _api_headers() -> dict:
    """Return the headers required for direct API-Football."""
    return {
        "x-apisports-key": API_FOOTBALL_KEY,
    }


def _api_get(endpoint: str, params: dict) -> dict | None:
    """Make a synchronous GET request to the API-Football endpoint."""
    url = f"{API_FOOTBALL_BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, headers=_api_headers(), params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        logger.error(f"API-Football request failed: {e}")
        return None


async def api_get_async(endpoint: str, params: dict) -> dict | None:
    """Async wrapper around the API call with rate limiting."""
    async with _api_semaphore:
        await asyncio.sleep(0.5)  # Small delay to respect rate limits
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _api_get, endpoint, params)


async def fetch_today_fixtures() -> list[dict]:
    """Fetch all of today's fixtures across all leagues."""
    today = datetime.now().strftime("%Y-%m-%d")
    data = await api_get_async("fixtures", {"date": today})
    if data and data.get("response"):
        return data["response"]
    return []


async def fetch_team_stats(team_id: int, league_id: int) -> dict | None:
    """Fetch team statistics for the current season."""
    data = await api_get_async(
        "teams/statistics",
        {"team": team_id, "league": league_id, "season": CURRENT_SEASON},
    )
    if data and data.get("response"):
        return data["response"]
    return None


async def fetch_team_form(team_id: int, league_id: int = None) -> list[dict]:
    """Fetch the last 5 completed fixtures for a team.

    Free plan doesn't support 'last' param, so we fetch by season
    and filter to completed matches, taking the most recent 5.
    """
    if league_id:
        data = await api_get_async(
            "fixtures",
            {"team": team_id, "league": league_id, "season": 2025},
        )
    else:
        # Fallback: fetch from current season fixtures
        data = await api_get_async(
            "fixtures",
            {"team": team_id, "season": 2025},
        )
    if data and data.get("response"):
        # Filter to completed matches, sort newest first, take last 5
        completed = [
            fx for fx in data["response"]
            if fx.get("fixture", {}).get("status", {}).get("short") in ("FT", "AET", "PEN")
        ]
        # Sort by date descending (newest first)
        completed.sort(key=lambda x: x.get("fixture", {}).get("timestamp", 0), reverse=True)
        return completed[:5]
    return []


# =============================================================================
# BETTING ANALYSIS ENGINE
# =============================================================================


def _extract_form_string(fixtures: list[dict], team_id: int) -> str:
    """Extract a form string (e.g., 'WWDLW') from recent fixtures for a team."""
    form_chars = []
    # Fixtures are returned newest first; reverse for chronological order
    for fx in reversed(fixtures):
        home = fx["teams"]["home"]
        away = fx["teams"]["away"]
        home_goals = fx["goals"]["home"]
        away_goals = fx["goals"]["away"]

        if home_goals is None or away_goals is None:
            continue

        if home["id"] == team_id:
            if home_goals > away_goals:
                form_chars.append("W")
            elif home_goals == away_goals:
                form_chars.append("D")
            else:
                form_chars.append("L")
        else:
            if away_goals > home_goals:
                form_chars.append("W")
            elif away_goals == home_goals:
                form_chars.append("D")
            else:
                form_chars.append("L")
    return "".join(form_chars)


def _form_score(form: str) -> float:
    """Convert a form string to a numeric score. W=3, D=1, L=0."""
    if not form:
        return 0.0
    total = sum(3 if c == "W" else 1 if c == "D" else 0 for c in form)
    return total / len(form)


def _parse_goals_stat(stats: dict, side: str, metric: str) -> float:
    """Parse average goals scored or conceded from team statistics.

    API-Football response structure:
        goals -> {for|against} -> average -> {home|away|total} -> "1.5"

    Args:
        stats: Team statistics dict from API-Football.
        side: 'home', 'away', or 'total'.
        metric: 'for' or 'against'.
    """
    try:
        goals_section = stats.get("goals", {})
        metric_section = goals_section.get(metric, {})
        avg_section = metric_section.get("average", {})
        val = avg_section.get(side)
        if val is not None:
            return float(val)
    except (KeyError, TypeError, ValueError):
        pass
    return 0.0


async def analyze_match(fixture: dict, league_id: int):
    """Elite analysis: fetch form + stats, run edge scoring, return MatchEdge if score >= 7."""
    home = fixture["teams"]["home"]
    away = fixture["teams"]["away"]
    home_id = home["id"]
    away_id = away["id"]

    home_fixtures = await fetch_team_form(home_id)
    away_fixtures = await fetch_team_form(away_id)

    if len(home_fixtures) < 3 or len(away_fixtures) < 3:
        return None

    home_stats = await fetch_team_stats(home_id, league_id)
    away_stats = await fetch_team_stats(away_id, league_id)

    home_metrics = extract_team_metrics(
        home_fixtures, home_id, home["name"], home_stats
    )
    away_metrics = extract_team_metrics(
        away_fixtures, away_id, away["name"], away_stats
    )

    competition = fixture.get("league", {}).get("name", f"League {league_id}")
    match_time = fixture.get("fixture", {}).get("date", "TBD")

    return analyze_match_edge(home_metrics, away_metrics, competition, match_time)


async def generate_safe_picks():
    """Generate picks using SportyBet odds + SofaScore form + elite analysis."""
    from sofascore_scraper import scrape_pregame_form
    from elite_engine import TeamMetrics, analyze_match_edge
    from research_agent import extract_market_signals, _form_from_ppg, _estimate_conceded
    from sportybet_scraper import fetch_upcoming_events, analyze_all_markets

    loop = asyncio.get_event_loop()

    # Step 1: Get SportyBet events with odds
    events = await loop.run_in_executor(None, fetch_upcoming_events, 100, 1, False)
    if not events:
        return {"top_10": [], "slips": {"slip_a": [], "slip_b": [], "slip_c": [], "combined": {}}}

    # Step 2: For each event, try SofaScore form scraping + elite analysis
    edges = []
    scraper_plays = []

    for ev in events[:30]:
        h = ev["home"]
        a = ev["away"]
        league = ev.get("league", "")
        markets = ev.get("markets", {})
        ox = markets.get("1X2", {})
        home_odds = ox.get("Home", 0)
        away_odds = ox.get("Away", 0)
        draw_odds = ox.get("Draw", 0)

        if not home_odds:
            continue

        # Also run the scraper's market analysis
        analysis = await loop.run_in_executor(None, analyze_all_markets, ev)
        for play in analysis.get("plays", []):
            play["event_id"] = ev.get("event_id", "")
            play["league"] = league
            play["home"] = h
            play["away"] = a
            play["start_time_ms"] = ev.get("start_time_ms", 0)
            scraper_plays.append(play)

        # Elite analysis using market signals
        market = extract_market_signals({"Home": home_odds, "Draw": draw_odds, "Away": away_odds})
        hm = TeamMetrics(
            name=h, form=_form_from_ppg(market.get("home_form_ppg", 1.5)),
            ppg=market.get("home_form_ppg", 1.5),
            goals_scored_avg=market.get("home_form_ppg", 1.5),
            goals_conceded_avg=_estimate_conceded(market.get("home_form_ppg", 1.5)),
        )
        am = TeamMetrics(
            name=a, form=_form_from_ppg(market.get("away_form_ppg", 1.5)),
            ppg=market.get("away_form_ppg", 1.5),
            goals_scored_avg=market.get("away_form_ppg", 1.5),
            goals_conceded_avg=_estimate_conceded(market.get("away_form_ppg", 1.5)),
        )
        edge = analyze_match_edge(hm, am, league, ev.get("start_time_ms", ""))
        if edge:
            edges.append(edge)

    # Step 3: Combine scraper plays + elite edges
    # Use scraper plays as primary (they're proven to work)
    scraper_plays.sort(key=lambda p: p["score"], reverse=True)

    # Select top plays with diversity
    top_10 = []
    match_count = {}
    market_count = {}
    for play in scraper_plays:
        eid = play.get("event_id", "")
        mkt = play["market"]
        if match_count.get(eid, 0) >= 2:
            continue
        if market_count.get(mkt, 0) >= 3:
            continue
        top_10.append(play)
        match_count[eid] = match_count.get(eid, 0) + 1
        market_count[mkt] = market_count.get(mkt, 0) + 1
        if len(top_10) >= 10:
            break

    # Build slips
    import functools
    slips = {"a": [], "b": [], "c": []}
    used = set()

    def fill(key, target_max, max_legs):
        for play in top_10:
            if len(slips[key]) >= max_legs:
                break
            if play.get("event_id", "") in used:
                continue
            current = functools.reduce(lambda x, y: x * y, [p["odds"] for p in slips[key]], 1.0)
            if current * play["odds"] > target_max * 1.8:
                continue
            slips[key].append(play)
            used.add(play.get("event_id", ""))

    fill("a", 3.0, 2)
    fill("b", 7.0, 3)
    fill("c", 11.0, 5)

    combined = {}
    for key in ["a", "b", "c"]:
        if slips[key]:
            combined[key] = round(functools.reduce(lambda x, y: x * y, [p["odds"] for p in slips[key]], 1.0), 2)
        else:
            combined[key] = 0

    return {
        "top_10": top_10,
        "slips": {"slip_a": slips["a"], "slip_b": slips["b"], "slip_c": slips["c"], "combined": combined},
        "elite_edges": len(edges),
    }



async def _ensure_private(update: Update) -> bool:
    """Return True if the chat is private; send a warning and return False otherwise."""
    if update.effective_chat and update.effective_chat.type != "private":
        return False
    return True


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /start command."""
    if not await _ensure_private(update):
        return

    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "User"

    if is_vip(user_id):
        vip_info = get_vip_info(user_id)
        expiry = vip_info["expiry_date"] if vip_info else "Unknown"
        status_text = f"✅ *VIP Active* — Expires: `{expiry}`"
    else:
        status_text = (
            f"❌ *Not a VIP*\n"
            f"Pay ₦500/week to unlock premium picks:\n"
            f"[Pay Now]({PAYSTACK_LINK})"
        )

    welcome = (
        f"⚽ *Welcome to SportyBot, {username}!*\n\n"
        f"{status_text}\n\n"
        f"*Available Commands:*\n"
        f"/safe — Get today's curated safe picks\n"
        f"/optimize — Upload a betting slip for optimization (VIP)\n"
        f"/status — View your VIP subscription status\n\n"
        f"_Data powered by API-Football_"
    )

    await update.message.reply_text(welcome, parse_mode="Markdown", disable_web_page_preview=True)


async def cmd_safe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /safe command — return daily curated safe picks."""
    if not await _ensure_private(update):
        return

    user_id = update.effective_user.id
    if not is_vip(user_id):
        await update.message.reply_text(
            f"❌ You are not a VIP. Pay ₦500/week to get access: {PAYSTACK_LINK}",
            disable_web_page_preview=True,
        )
        return

    # Notify user that analysis is in progress
    progress_msg = await update.message.reply_text("⏳ Fetching today's matches and analyzing stats...")

    try:
        picks = await generate_safe_picks()
    except Exception as e:
        logger.error(f"Error generating safe picks: {e}")
        await progress_msg.edit_text("An error occurred while fetching picks. Please try again later.")
        return

    top = picks.get("top_10", [])
    slips = picks.get("slips", {})

    if not top:
        await progress_msg.edit_text(
            "No qualifying picks found today. Try again later."
        )
        return

    msg = "VIP DAILY PICKS\n"
    msg += "=" * 24 + "\n\n"

    for i, p in enumerate(top, 1):
        ts = "TBD"
        if p.get("start_time_ms"):
            try:
                ts = datetime.fromtimestamp(p["start_time_ms"] / 1000).strftime("%H:%M UTC")
            except:
                pass
        tier = p.get("tier", "B")
        msg += f"{i}. {p['home']} vs {p['away']}\n"
        msg += f"   {p['league']} | {ts}\n"
        msg += f"   {p['market']}: {p['pick']} @ {p['odds']:.2f}\n"
        msg += f"   Implied: {p['implied']}% | Tier: {tier}\n\n"

    for key, label, risk in [("slip_a", "SLIP A", "SAFE"), ("slip_b", "SLIP B", "MODERATE"), ("slip_c", "SLIP C", "HIGH")]:
        slip = slips.get(key, [])
        combined = slips.get("combined", {}).get(key[-1], 0)
        if slip:
            msg += f"--- {label} ({combined:.1f}x) - {risk} ---\n"
            for p in slip:
                msg += f"  {p['home']} vs {p['away']}: {p['pick']} @ {p['odds']:.2f}\n"
            msg += "\n"

    msg += "Upgrade to VIP for daily optimized picks!\n"
    msg += "DM the admin to verify your payment and get access."

    if len(msg) > 4000:
        await progress_msg.edit_text(msg[:4000])
        await update.message.reply_text(msg[4000:])
    else:
        await progress_msg.edit_text(msg)


async def cmd_optimize(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /optimize command — instruct user to upload a screenshot."""
    if not await _ensure_private(update):
        return

    user_id = update.effective_user.id
    if not is_vip(user_id):
        await update.message.reply_text(
            f"❌ You are not a VIP. Pay ₦500/week to get access: {PAYSTACK_LINK}",
            disable_web_page_preview=True,
        )
        return

    await update.message.reply_text(
        "📸 *Slip Optimizer*\n\n"
        "Upload a screenshot of your betting slip and I'll analyze it for you.\n\n"
        "I will:\n"
        "• Extract teams and odds from your slip\n"
        "• Check each pick against live stats\n"
        "• Flag risky selections\n"
        "• Suggest safer alternatives\n\n"
        "_Just send the image as a photo._",
        parse_mode="Markdown",
    )


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle uploaded photos — run OCR and analyze the betting slip."""
    if not await _ensure_private(update):
        return

    user_id = update.effective_user.id
    if not is_vip(user_id):
        await update.message.reply_text(
            f"❌ You are not a VIP. Pay ₦500/week to get access: {PAYSTACK_LINK}",
            disable_web_page_preview=True,
        )
        return

    progress_msg = await update.message.reply_text("⏳ Processing your betting slip...")

    # Download the largest photo
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)

    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
        await file.download_to_drive(tmp_path)

    try:
        # Run OCR
        await progress_msg.edit_text("⏳ Running OCR on the image...")
        extracted_text = extract_text_from_image(tmp_path)

        if not extracted_text.strip():
            await progress_msg.edit_text(
                "❌ Could not extract any text from the image.\n"
                "Please upload a clearer screenshot."
            )
            return

        # Parse the extracted text
        await progress_msg.edit_text("⏳ Analyzing extracted text...")
        parsed_picks = parse_slip_text(extracted_text)

        if not parsed_picks:
            await progress_msg.edit_text(
                "❌ Could not identify any betting picks from the image.\n\n"
                f"*Extracted text:*\n```\n{extracted_text[:500]}\n```\n\n"
                "Please upload a clearer screenshot or ensure the slip shows teams and odds clearly.",
                parse_mode="Markdown",
            )
            return

        # Assess risk
        assessed_picks = assess_slip_risk(parsed_picks)

        # Format response
        header = "🔍 *Slip Analysis*\n" + "=" * 30 + "\n\n"
        body_parts = []
        risky_count = 0

        for i, pick in enumerate(assessed_picks, 1):
            risk_emoji = {"SAFE": "🟢", "MODERATE": "🟡", "RISKY": "🔴"}.get(pick["risk_level"], "⚪")
            team_str = ""
            if pick["team1"] and pick["team2"]:
                team_str = f"{pick['team1']} vs {pick['team2']}"

            if pick["risk_level"] == "RISKY":
                risky_count += 1

            line = (
                f"*{i}. {team_str or pick['bet_type']}*\n"
                f"   🎯 Bet: {pick['bet_type']} @ {pick['odds']}\n"
                f"   {risk_emoji} Risk: *{pick['risk_level']}*\n"
            )

            if pick["risk_flags"]:
                line += f"   ⚠️ Flags: {', '.join(pick['risk_flags'])}\n"
                alternative = suggest_safer_alternative(pick)
                line += f"   ✅ Suggestion: {alternative}\n"

            body_parts.append(line)

        # Summary
        total = len(assessed_picks)
        safe_count = sum(1 for p in assessed_picks if p["risk_level"] == "SAFE")
        mod_count = sum(1 for p in assessed_picks if p["risk_level"] == "MODERATE")

        summary = (
            f"\n📋 *Summary*\n"
            f"Total picks: {total}\n"
            f"🟢 Safe: {safe_count} | 🟡 Moderate: {mod_count} | 🔴 Risky: {risky_count}\n"
        )

        if risky_count > 0:
            summary += (
                f"\n⚠️ *{risky_count} risky pick(s) detected.*\n"
                f"Consider the suggestions above to reduce your risk."
            )
        else:
            summary += "\n✅ All picks look reasonable. Good luck!"

        full_text = header + "\n".join(body_parts) + summary

        if len(full_text) > 4000:
            await progress_msg.edit_text(header, parse_mode="Markdown")
            chunk = ""
            for part in body_parts:
                if len(chunk) + len(part) > 3900:
                    await update.message.reply_text(chunk, parse_mode="Markdown")
                    chunk = part
                else:
                    chunk += part + "\n"
            if chunk:
                await update.message.reply_text(chunk, parse_mode="Markdown")
            await update.message.reply_text(summary, parse_mode="Markdown")
        else:
            await progress_msg.edit_text(full_text, parse_mode="Markdown")

    except Exception as e:
        logger.error(f"Error processing photo: {e}")
        await progress_msg.edit_text(
            "❌ An error occurred while processing your slip. Please try again."
        )
    finally:
        # Clean up temp file
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /status command — show VIP subscription info."""
    if not await _ensure_private(update):
        return

    user_id = update.effective_user.id
    vip_info = get_vip_info(user_id)

    if vip_info is None:
        await update.message.reply_text(
            f"❌ You don't have a VIP subscription.\n"
            f"Pay ₦500/week to get access: {PAYSTACK_LINK}",
            disable_web_page_preview=True,
        )
        return

    expiry = datetime.strptime(vip_info["expiry_date"], "%Y-%m-%d %H:%M:%S")
    now = datetime.now()

    if now < expiry:
        remaining = expiry - now
        days = remaining.days
        hours = remaining.seconds // 3600
        status = "✅ *Active*"
        remaining_str = f"{days}d {hours}h remaining"
    else:
        status = "❌ *Expired*"
        remaining_str = "Subscription has ended"

    added = datetime.strptime(vip_info["added_date"], "%Y-%m-%d %H:%M:%S")

    msg = (
        f"👤 *VIP Status*\n\n"
        f"Username: @{vip_info['username']}\n"
        f"User ID: `{user_id}`\n"
        f"Status: {status}\n"
        f"Member since: {added.strftime('%Y-%m-%d')}\n"
        f"Expires: {vip_info['expiry_date']}\n"
        f"⏰ {remaining_str}\n"
    )

    if now >= expiry:
        msg += f"\n[Renew Now]({PAYSTACK_LINK})"

    await update.message.reply_text(msg, parse_mode="Markdown", disable_web_page_preview=True)


# =============================================================================
# ADMIN COMMANDS
# =============================================================================


async def cmd_addvip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /addvip <user_id> [weeks] — admin only."""
    if not await _ensure_private(update):
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ You don't have permission to use this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/addvip <user_id> [weeks]`\n"
            "Example: `/addvip 123456789 4` (adds 4 weeks)",
            parse_mode="Markdown",
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    weeks = 1
    if len(args) > 1:
        try:
            weeks = int(args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid weeks value. Must be a number.")
            return

    expiry_str = add_vip(target_user_id, f"user_{target_user_id}", weeks)
    await update.message.reply_text(
        f"✅ VIP added successfully!\n\n"
        f"User ID: `{target_user_id}`\n"
        f"Duration: {weeks} week(s)\n"
        f"Expires: {expiry_str}",
        parse_mode="Markdown",
    )


async def cmd_removevip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /removevip <user_id> — admin only."""
    if not await _ensure_private(update):
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ You don't have permission to use this command.")
        return

    args = context.args
    if not args:
        await update.message.reply_text(
            "Usage: `/removevip <user_id>`",
            parse_mode="Markdown",
        )
        return

    try:
        target_user_id = int(args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. Must be a number.")
        return

    if remove_vip(target_user_id):
        await update.message.reply_text(
            f"✅ VIP removed for user `{target_user_id}`.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"⚠️ User `{target_user_id}` was not in the VIP list.",
            parse_mode="Markdown",
        )


async def cmd_listvip(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /listvip — admin only. Lists all VIP users."""
    if not await _ensure_private(update):
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ You don't have permission to use this command.")
        return

    vips = list_all_vips()
    if not vips:
        await update.message.reply_text("📋 No VIP users in the database.")
        return

    lines = ["📋 *VIP Users*\n"]
    for v in vips:
        status = "✅" if v["active"] else "❌"
        lines.append(
            f"{status} `{v['user_id']}` @{v['username']} — expires {v['expiry_date']}"
        )

    msg = "\n".join(lines)
    if len(msg) > 4000:
        msg = msg[:3990] + "\n..."

    await update.message.reply_text(msg, parse_mode="Markdown")


async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /refresh — admin only. Runs the full pipeline to generate fresh picks."""
    if not await _ensure_private(update):
        return

    admin_id = update.effective_user.id
    if admin_id not in ADMIN_USER_IDS:
        await update.message.reply_text("⛔ You don't have permission to use this command.")
        return

    progress_msg = await update.message.reply_text("⏳ Running pipeline... Scraping matches, scoring, and generating picks.")

    try:
        from core.pipeline import run_full_pipeline, format_for_telegram
        output = run_full_pipeline(today_only=True)

        summary = output.get("summary", {})
        matches = summary.get("qualified_matches", 0)
        total = summary.get("total_picks_generated", 0)
        safe_count = len(output.get("safe_slip", []))
        mod_count = len(output.get("moderate_slip", []))
        high_count = len(output.get("high_slip", []))

        await progress_msg.edit_text(
            f"✅ *Picks Refreshed*\n\n"
            f"Matches analyzed: {summary.get('total_events_scraped', 0)}\n"
            f"Qualified: {matches}\n"
            f"Total picks: {total}\n\n"
            f"Safe: {safe_count} picks\n"
            f"Moderate: {mod_count} picks\n"
            f"High: {high_count} picks\n\n"
            f"Use /safe to view picks.",
            parse_mode="Markdown",
        )

    except Exception as e:
        logger.error(f"Refresh error: {e}")
        await progress_msg.edit_text(f"❌ Pipeline error: {e}")


# =============================================================================
# ERROR HANDLER
# =============================================================================


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify the user if possible."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    if isinstance(update, Update):
        msg = update.effective_message  # type: ignore[union-attr]
        if msg:
            await msg.reply_text(
                "❌ Something went wrong. Please try again later."
            )


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================


def main() -> None:
    """Initialize and start the bot."""
    # Initialize the database
    init_db()

    # Build the application
    app = Application.builder().token(BOT_TOKEN).build()

    # Register command handlers
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("safe", cmd_safe))
    app.add_handler(CommandHandler("optimize", cmd_optimize))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("addvip", cmd_addvip))
    app.add_handler(CommandHandler("removevip", cmd_removevip))
    app.add_handler(CommandHandler("listvip", cmd_listvip))
    app.add_handler(CommandHandler("refresh", cmd_refresh))

    # Register photo handler for slip optimization
    app.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_photo))

    # Register error handler
    app.add_error_handler(error_handler)

    logger.info("SportyBot is starting...")
    print("SportyBot is running. Press Ctrl+C to stop.")

    # Start polling
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
