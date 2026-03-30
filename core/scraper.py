"""
Enhanced Multi-Market Scraper
=============================
Collects match data with 20-25+ betting markets per match from SportyBet API.
Falls back to Flashscore via Playwright for fixture data.
"""

import time
import logging
import requests
import asyncio
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sportybet.com/ng/sport/football",
    "clientid": "web",
    "operid": "2",
    "Accept-Language": "en",
    "Platform": "web",
}
BASE_URL = "https://www.sportybet.com/api/ng/factsCenter"

# Market IDs that the SportyBet API supports
MARKET_IDS = "1,18,10,29,11,26,36,14,60100"


def fetch_events_with_all_markets(page_size: int = 200, page_num: int = 1, today_only: bool = True) -> list[dict]:
    """Fetch events with maximum market coverage from SportyBet API.

    Returns list of event dicts with full market data.
    """
    ts = int(time.time() * 1000)
    try:
        params = {
            "sportId": "sr:sport:1",
            "marketId": MARKET_IDS,
            "pageSize": str(page_size),
            "pageNum": str(page_num),
            "option": "1",
            "_t": ts,
        }
        if today_only:
            params["todayGames"] = "true"

        r = requests.get(f"{BASE_URL}/pcUpcomingEvents", headers=HEADERS, params=params, timeout=20)
        data = r.json()

        biz_code = str(data.get("bizCode", ""))
        if biz_code != "10000":
            logger.warning(f"API returned bizCode: {biz_code} - trying without todayGames filter")
            # Fallback: try without todayGames filter
            if today_only:
                params.pop("todayGames", None)
                r = requests.get(f"{BASE_URL}/pcUpcomingEvents", headers=HEADERS, params=params, timeout=20)
                data = r.json()
                biz_code = str(data.get("bizCode", ""))
                if biz_code != "10000":
                    logger.warning(f"API still returned bizCode: {biz_code}")
                    return []

        events = []
        for tournament in data.get("data", {}).get("tournaments", []):
            league_name = tournament.get("name", "Unknown")
            for event in tournament.get("events", []):
                if not isinstance(event, dict):
                    continue

                markets = _extract_all_markets(event)

                events.append({
                    "event_id": event.get("eventId", ""),
                    "game_id": event.get("gameId", ""),
                    "league": league_name,
                    "home": event.get("homeTeamName", ""),
                    "away": event.get("awayTeamName", ""),
                    "start_time_ms": event.get("estimateStartTime", 0),
                    "markets": markets,
                    "market_count": len(markets),
                })

        logger.info(f"Fetched {len(events)} events with avg {sum(e['market_count'] for e in events) / max(len(events), 1):.1f} markets each")

        if today_only:
            events = _filter_today(events)

        return events

    except Exception as ex:
        logger.error(f"API error: {ex}")
        return []


def _extract_all_markets(event: dict) -> dict:
    """Extract all available markets from an event, normalizing names."""
    markets = {}

    for m in event.get("markets", []):
        if not isinstance(m, dict):
            continue

        m_desc = m.get("desc", "")
        m_spec = m.get("specifier", "")
        key = f"{m_desc}({m_spec})" if m_spec else m_desc

        outcomes = {}
        for o in m.get("outcomes", []):
            if not isinstance(o, dict):
                continue
            try:
                odds_val = float(o.get("odds", 0))
                if odds_val > 0:
                    outcomes[o.get("desc", "")] = odds_val
            except (ValueError, TypeError):
                pass

        if outcomes:
            # Normalize market key
            normalized_key = _normalize_market_key(key)
            markets[normalized_key] = outcomes

    return markets


def _normalize_market_key(key: str) -> str:
    """Normalize market names to consistent format."""
    mappings = {
        "Match Result": "1X2",
        "Match Winner": "1X2",
        "Home/Away": "1X2",
        "Both Teams To Score": "BTTS",
        "Both teams to score": "BTTS",
        "Goal/No Goal": "BTTS",
        "GG/NG": "BTTS",
    }
    for old, new in mappings.items():
        if key.startswith(old):
            return new + key[len(old):]
    return key


def _filter_today(events: list[dict]) -> list[dict]:
    """Filter events to today only."""
    now = datetime.now()
    ts_start = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
    ts_end = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp() * 1000)

    today_events = [e for e in events if ts_start <= e.get("start_time_ms", 0) < ts_end]
    logger.info(f"Filtered to {len(today_events)} events today")
    return today_events


async def scrape_flashscore_fixtures() -> list[dict]:
    """Scrape fixtures from Flashscore using Playwright as supplementary source."""
    results = []

    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto("https://www.flashscore.com/football/", wait_until="networkidle", timeout=45000)
            except Exception as e:
                logger.error(f"Failed to load Flashscore: {e}")
                await browser.close()
                return results

            await page.wait_for_timeout(3000)

            # Scroll to load lazy content
            for _ in range(20):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(800)

            data = await page.evaluate("""() => {
                const matches = [];
                let currentLeague = '';
                let currentCountry = '';
                const sections = document.querySelectorAll('.sportName.soccer');

                for (const soccer of sections) {
                    for (const child of soccer.children) {
                        const cls = child.className || '';
                        if (cls.includes('headerLeague__wrapper')) {
                            const link = child.querySelector('a[href*="/football/"]');
                            if (link) currentLeague = link.textContent.trim();
                            const text = child.textContent.trim();
                            const cm = text.match(/([A-Z][A-Z\\\\s&]+):/);
                            if (cm) currentCountry = cm[1].trim();
                            continue;
                        }
                        if (cls.includes('event__match')) {
                            const homeEl = child.querySelector('[class*="homeParticipant"]');
                            const awayEl = child.querySelector('[class*="awayParticipant"]');
                            if (!homeEl || !awayEl) continue;
                            let time = '';
                            const timeEl = child.querySelector('[class*="event__time"]');
                            if (timeEl) time = timeEl.textContent.trim();
                            let status = 'scheduled';
                            if (cls.includes('live')) status = 'live';
                            else if (cls.includes('finished')) status = 'finished';
                            matches.push({
                                league: currentLeague, country: currentCountry,
                                home: homeEl.textContent.trim(), away: awayEl.textContent.trim(),
                                time: time, status: status,
                            });
                        }
                    }
                }
                return matches;
            }""")

            await browser.close()

            if data:
                for match in data:
                    results.append({
                        "league": match.get("league", "Unknown"),
                        "country": match.get("country", ""),
                        "home": match.get("home", ""),
                        "away": match.get("away", ""),
                        "time": match.get("time", ""),
                        "status": match.get("status", "scheduled"),
                        "source": "flashscore",
                    })

    except ImportError:
        logger.warning("Playwright not installed, skipping Flashscore scrape")
    except Exception as e:
        logger.error(f"Flashscore scrape error: {e}")

    logger.info(f"Scraped {len(results)} fixtures from Flashscore")
    return results


def fetch_comprehensive_data(today_only: bool = True) -> list[dict]:
    """Main entry: fetch all match data with maximum market coverage."""
    events = fetch_events_with_all_markets(page_size=200, today_only=today_only)
    logger.info(f"Comprehensive fetch: {len(events)} events with markets")
    return events


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    events = fetch_comprehensive_data()
    print(f"\nFetched {len(events)} events\n")
    for ev in events[:5]:
        print(f"  {ev['home']} vs {ev['away']} | {ev['league']} | {ev['market_count']} markets")
        for mk, outcomes in list(ev['markets'].items())[:3]:
            print(f"    {mk}: {outcomes}")
