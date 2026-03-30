"""
Flashscore Research Module
=========================
Scrapes flashscore for fixtures + team form data.
"""

import logging
import time
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def scrape_flashscore_week(days_ahead=7):
    """Scrape Flashscore for fixtures for next N days."""
    from playwright.sync_api import sync_playwright

    all_matches = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)

            for day_offset in range(days_ahead):
                target_date = datetime.now() + timedelta(days=day_offset)
                date_str = target_date.strftime("%Y-%m-%d")
                day_label = target_date.strftime("%A")

                logger.info(f"Flashscore: scraping {day_label} {date_str}")

                url = f"https://www.flashscore.com/{date_str}/"
                try:
                    page = browser.new_page()
                    page.goto(url, timeout=20000)
                except Exception as e:
                    logger.warning(f"Failed to load {url}: {e}")
                    continue

                time.sleep(3)

                for i in range(3):
                    page.evaluate(f"window.scrollTo(0, {(i+1)*500})")
                    time.sleep(0.5)

                matches = page.evaluate("""() => {
                    const results = [];
                    
                    // Get all event containers
                    const events = document.querySelectorAll('[id^="g_1_"]');
                    
                    for (const ev of events) {
                        try {
                            const home = ev.getAttribute('data-home');
                            const away = ev.getAttribute('data-away');
                            const league = ev.getAttribute('data-league') || '';
                            
                            if (home && away) {
                                results.push({
                                    home: home,
                                    away: away,
                                    league: league
                                });
                            }
                        } catch(e) {}
                    }
                    
                    return results;
                }""")

                logger.info(f"  Found {len(matches)} matches on {day_label}")
                all_matches.extend(matches)
                page.close()

            browser.close()

    except Exception as e:
        logger.error(f"Flashscore scrape failed: {e}")

    logger.info(f"Flashscore: total {len(all_matches)} matches scraped")
    return all_matches


def get_form_for_team(team_name: str) -> dict:
    """Get form data for a specific team from Flashscore."""
    from playwright.sync_api import sync_playwright

    result = {
        "form": "",
        "goals_scored": 1.3,
        "goals_conceded": 1.2,
        "position": 0,
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()

            search_url = f"https://www.flashscore.com/search/{team_name.replace(' ', '-').lower()}"
            page.goto(search_url, timeout=15000)
            time.sleep(2)

            form_data = page.evaluate("""() => {
                const formEls = document.querySelectorAll('.form-row .form-result, .team-form span');
                const form = [];
                for (let i = 0; i < Math.min(5, formEls.length); i++) {
                    const t = formEls[i].innerText?.trim().toUpperCase();
                    if (t === 'W' || t === 'D' || t === 'L') form.push(t);
                }
                return form.join('');
            }""")

            if form_data:
                result["form"] = form_data

            browser.close()

    except Exception as e:
        logger.debug(f"Form lookup failed for {team_name}: {e}")

    return result
