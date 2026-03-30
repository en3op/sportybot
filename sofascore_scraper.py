"""
SofaScore Playwright Scraper
=============================
Scrapes match form data by loading SofaScore match pages via Playwright
and intercepting the pregame-form API response.

Returns: form (last 5), league position, avg rating.
"""

import re
import json
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def get_team_goals_from_events(page, team_id: int) -> dict:
    """Get goals scored/conceded from a team's last 5 events via SofaScore API.

    Must be called from within a Playwright page context that has loaded
    sofascore.com (for cookies/CORS).
    """
    result = page.evaluate('''async (teamId) => {
        try {
            const resp = await fetch(`https://api.sofascore.com/api/v1/team/${teamId}/events/last/0`);
            if (!resp.ok) return null;
            const data = await resp.json();
            const events = (data.events || []).slice(0, 5);
            let totalGF = 0, totalGA = 0, form = [];
            for (const ev of events) {
                const hs = ev.homeScore?.current || 0;
                const as = ev.awayScore?.current || 0;
                const isHome = ev.homeTeam?.id === teamId;
                const gf = isHome ? hs : as;
                const ga = isHome ? as : hs;
                totalGF += gf;
                totalGA += ga;
                form.push(gf > ga ? 'W' : gf === ga ? 'D' : 'L');
            }
            return {
                form: form.join(''),
                goals_scored: events.length > 0 ? +(totalGF / events.length).toFixed(2) : 0,
                goals_conceded: events.length > 0 ? +(totalGA / events.length).toFixed(2) : 0,
                matches: events.length,
            };
        } catch(e) { return null; }
    }''', team_id)

    return result or {"form": "", "goals_scored": 0, "goals_conceded": 0, "matches": 0}


def research_match_full(home_team: str, away_team: str) -> dict:
    """Full research: search SofaScore, get pregame-form + team goals.

    Returns dict with form, goals_scored, goals_conceded, position for both teams.
    """
    from playwright.sync_api import sync_playwright

    result = {
        "home": {"form": "", "goals_scored": 0.0, "goals_conceded": 0.0, "league_position": 0},
        "away": {"form": "", "goals_scored": 0.0, "goals_conceded": 0.0, "league_position": 0},
        "source": "sofascore",
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Capture pregame-form + find team IDs
            form_data = {}
            team_ids = {"home": 0, "away": 0}

            def on_resp(resp):
                nonlocal form_data, team_ids
                if "/pregame-form" in resp.url:
                    try:
                        form_data.update(resp.json())
                    except:
                        pass
                if "/event/" in resp.url and resp.url.endswith("/event"):
                    try:
                        data = resp.json()
                        ev = data.get("event", {})
                        team_ids["home"] = ev.get("homeTeam", {}).get("id", 0)
                        team_ids["away"] = ev.get("awayTeam", {}).get("id", 0)
                    except:
                        pass

            page.on('response', on_resp)

            # Load SofaScore homepage for cookies
            page.goto('https://www.sofascore.com/', timeout=15000)
            time.sleep(2)

            # Search for the match
            query = f"{home_team} {away_team}"
            page.goto(f"https://www.sofascore.com/search?q={query}", timeout=15000)
            time.sleep(2)

            # Find first match link
            links = page.query_selector_all('a[href*="/match/"]')
            match_url = None
            for link in links:
                href = link.get_attribute('href')
                if href:
                    match_url = f"https://www.sofascore.com{href}"
                    break

            if match_url:
                # Load match page
                page.goto(match_url, wait_until="domcontentloaded", timeout=15000)

                # Scroll to trigger lazy loads
                for i in range(4):
                    page.evaluate(f"window.scrollTo(0, {i * 300})")
                    time.sleep(1)
                time.sleep(2)

                # Parse pregame-form
                if "homeTeam" in form_data:
                    ht = form_data["homeTeam"]
                    at = form_data.get("awayTeam", {})
                    result["home"]["form"] = "".join(ht.get("form", []))
                    result["home"]["league_position"] = ht.get("position", 0)
                    result["away"]["form"] = "".join(at.get("form", []))
                    result["away"]["league_position"] = at.get("position", 0)

                # Get goals from team events
                if team_ids["home"] > 0:
                    home_goals = get_team_goals_from_events(page, team_ids["home"])
                    if home_goals["matches"] > 0:
                        result["home"]["goals_scored"] = home_goals["goals_scored"]
                        result["home"]["goals_conceded"] = home_goals["goals_conceded"]
                        if not result["home"]["form"]:
                            result["home"]["form"] = home_goals["form"]

                if team_ids["away"] > 0:
                    away_goals = get_team_goals_from_events(page, team_ids["away"])
                    if away_goals["matches"] > 0:
                        result["away"]["goals_scored"] = away_goals["goals_scored"]
                        result["away"]["goals_conceded"] = away_goals["goals_conceded"]
                        if not result["away"]["form"]:
                            result["away"]["form"] = away_goals["form"]

            browser.close()

    except Exception as e:
        logger.warning(f"Full research failed for {home_team} vs {away_team}: {e}")

    return result
    """Extract event ID from a SofaScore match URL."""
    m = re.search(r'#id:(\d+)', match_url)
    if m:
        return int(m.group(1))
    return None


def scrape_pregame_form(event_id: int) -> dict:
    """Scrape pregame form data for an event using Playwright.

    Loads the match page and intercepts the pregame-form API call.
    Returns dict with home/away form, position, avg_rating.
    """
    from playwright.sync_api import sync_playwright

    result = {
        "home": {"form": "", "position": 0, "avg_rating": 0.0},
        "away": {"form": "", "position": 0, "avg_rating": 0.0},
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Capture the pregame-form response
            form_data = {}
            def on_response(resp):
                nonlocal form_data
                if f"/event/{event_id}/pregame-form" in resp.url:
                    try:
                        form_data.update(resp.json())
                    except:
                        pass
            page.on('response', on_response)

            # Load the match page
            url = f"https://www.sofascore.com/event/{event_id}"
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            time.sleep(2)

            # Scroll to trigger lazy-loaded pregame-form API call
            page.evaluate("window.scrollTo(0, 500)")
            time.sleep(2)
            page.evaluate("window.scrollTo(0, 1000)")
            time.sleep(2)

            # Parse form data
            if "homeTeam" in form_data:
                ht = form_data["homeTeam"]
                at = form_data.get("awayTeam", {})
                result["home"]["form"] = "".join(ht.get("form", []))
                result["home"]["position"] = ht.get("position", 0)
                result["home"]["avg_rating"] = float(ht.get("avgRating", 0) or 0)
                result["away"]["form"] = "".join(at.get("form", []))
                result["away"]["position"] = at.get("position", 0)
                result["away"]["avg_rating"] = float(at.get("avgRating", 0) or 0)

            browser.close()

    except Exception as e:
        logger.warning(f"Playwright scrape failed for event {event_id}: {e}")

    return result


def get_event_id_from_url(match_url: str) -> Optional[int]:
    """Extract event ID from a SofaScore match URL."""
    import re
    m = re.search(r'#id:(\d+)', match_url)
    if m:
        return int(m.group(1))
    return None


def find_event_id(home_team: str, away_team: str) -> Optional[int]:
    """Search SofaScore for a match and return its event ID.

    Uses Playwright to search and extract the event ID from the URL.
    """
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            # Search for the match
            query = f"{home_team} {away_team}"
            page.goto(f"https://www.sofascore.com/search?q={query}", timeout=15000)
            time.sleep(2)

            # Find first match link
            links = page.query_selector_all('a[href*="/match/"]')
            for link in links:
                href = link.get_attribute('href')
                if href:
                    event_id = get_event_id_from_url(href)
                    if event_id:
                        browser.close()
                        return event_id

            browser.close()

    except Exception as e:
        logger.warning(f"Search failed for {home_team} vs {away_team}: {e}")

    return None


def research_match_sofascore(home_team: str, away_team: str) -> dict:
    """Full research for a match using SofaScore Playwright scraping.

    Finds the match, scrapes pregame form, returns structured data.
    """
    result = {
        "home": {"form": "", "goals_scored": 0.0, "goals_conceded": 0.0, "league_position": 0},
        "away": {"form": "", "goals_scored": 0.0, "goals_conceded": 0.0, "league_position": 0},
        "source": "sofascore",
    }

    # Find event ID
    event_id = find_event_id(home_team, away_team)
    if not event_id:
        return result

    # Get pregame form
    form_data = scrape_pregame_form(event_id)

    if form_data["home"]["form"]:
        result["home"]["form"] = form_data["home"]["form"]
        result["home"]["league_position"] = form_data["home"]["position"]

        # Estimate goals from form and rating
        form = form_data["home"]["form"]
        wins = form.count("W")
        result["home"]["goals_scored"] = round(0.5 + wins * 0.4, 1)
        losses = form.count("L")
        result["home"]["goals_conceded"] = round(0.3 + losses * 0.5, 1)

    if form_data["away"]["form"]:
        result["away"]["form"] = form_data["away"]["form"]
        result["away"]["league_position"] = form_data["away"]["position"]

        form = form_data["away"]["form"]
        wins = form.count("W")
        result["away"]["goals_scored"] = round(0.4 + wins * 0.35, 1)
        losses = form.count("L")
        result["away"]["goals_conceded"] = round(0.5 + losses * 0.5, 1)

    return result


def research_matches_batch(matches: list[dict], max_matches: int = 20) -> dict:
    """Research multiple matches in a single Playwright session.

    Args:
        matches: List of dicts with 'home' and 'away' team names.
        max_matches: Maximum matches to research (default 20 for performance).

    Returns dict keyed by "home_vs_away" with form data.
    """
    from playwright.sync_api import sync_playwright

    results = {}
    matches_to_process = matches[:max_matches]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for idx, match in enumerate(matches_to_process):
                home = match.get("home", "")
                away = match.get("away", "")
                if not home or not away:
                    continue
                key = f"{home} vs {away}"

                page = browser.new_page()

                # Capture pregame-form
                form_data = {}
                def make_handler(fd):
                    def on_resp(resp):
                        if "/pregame-form" in resp.url:
                            try:
                                fd.update(resp.json())
                            except:
                                pass
                    return on_resp

                page.on('response', make_handler(form_data))

                # Search for match with short timeout
                query = f"{home} {away}"
                try:
                    page.goto(f"https://www.sofascore.com/search?q={query}", timeout=8000)
                    time.sleep(1)

                    # Find match link
                    links = page.query_selector_all('a[href*="/match/"]')
                    event_url = None
                    for link in links:
                        href = link.get_attribute('href')
                        if href:
                            event_url = f"https://www.sofascore.com{href}"
                            break

                    if event_url:
                        page.goto(event_url, wait_until="domcontentloaded", timeout=8000)
                        time.sleep(2)

                except Exception as e:
                    logger.warning(f"Timeout for {key}: {e}")

                page.close()

                # Parse results
                home_form = ""
                away_form = ""
                home_pos = 0
                away_pos = 0

                if "homeTeam" in form_data:
                    ht = form_data["homeTeam"]
                    at = form_data.get("awayTeam", {})
                    home_form = "".join(ht.get("form", []))
                    away_form = "".join(at.get("form", []))
                    home_pos = ht.get("position", 0)
                    away_pos = at.get("position", 0)

                results[key] = {
                    "home": {
                        "form": home_form,
                        "goals_scored": round(0.5 + home_form.count("W") * 0.4, 1) if home_form else 0,
                        "goals_conceded": round(0.3 + home_form.count("L") * 0.5, 1) if home_form else 0,
                        "league_position": home_pos,
                    },
                    "away": {
                        "form": away_form,
                        "goals_scored": round(0.4 + away_form.count("W") * 0.35, 1) if away_form else 0,
                        "goals_conceded": round(0.5 + away_form.count("L") * 0.5, 1) if away_form else 0,
                        "league_position": away_pos,
                    },
                    "source": "sofascore",
                }
                
                logger.info(f"[{idx+1}/{len(matches_to_process)}] {key}: form={home_form}/{away_form}")

            browser.close()

    except Exception as e:
        logger.error(f"Batch research failed: {e}")

    return results
