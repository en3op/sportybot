"""
Web scraper for today's football fixtures from Flashscore.
Uses Playwright to render the JavaScript-heavy page.
"""

import asyncio
import logging

from playwright.async_api import async_playwright

logger = logging.getLogger(__name__)


async def scrape_fixtures() -> list[dict]:
    """Scrape today's football fixtures from Flashscore.

    Returns a list of dicts with keys:
        league, country, home, away, time, status
    """
    results = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        try:
            await page.goto(
                "https://www.flashscore.com/football/",
                wait_until="networkidle",
                timeout=45000,
            )
        except Exception as e:
            logger.error(f"Failed to load Flashscore: {e}")
            await browser.close()
            return results

        await page.wait_for_timeout(3000)

        # Scroll to load all lazy content
        for _ in range(30):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1000)

        data = await page.evaluate("""() => {
            const matches = [];
            let currentLeague = '';
            let currentCountry = '';

            // Get ALL soccer sections
            const sections = document.querySelectorAll('.sportName.soccer');

            for (const soccer of sections) {
                const children = soccer.children;

                for (const child of children) {
                    const cls = child.className || '';

                    // League header
                    if (cls.includes('headerLeague__wrapper')) {
                        const link = child.querySelector('a[href*="/football/"]');
                        if (link) currentLeague = link.textContent.trim();
                        const text = child.textContent.trim();
                        const countryMatch = text.match(/([A-Z][A-Z\\s&]+):/);
                        if (countryMatch) currentCountry = countryMatch[1].trim();
                        continue;
                    }

                    // Match row
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
                            league: currentLeague,
                            country: currentCountry,
                            home: homeEl.textContent.trim(),
                            away: awayEl.textContent.trim(),
                            time: time,
                            status: status,
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
                })

    logger.info(f"Scraped {len(results)} fixtures from Flashscore")
    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    fixtures = asyncio.run(scrape_fixtures())
    print(f"\nScraped {len(fixtures)} fixtures:\n")

    leagues = set((f["country"], f["league"]) for f in fixtures)
    print(f"Leagues ({len(leagues)}):")
    for country, league in sorted(leagues):
        count = sum(1 for f in fixtures if f["league"] == league)
        print(f"  [{country}] {league} ({count})")
    print()

    for f in fixtures[:30]:
        print(f"  [{f['country']}] {f['league']}: {f['home']} vs {f['away']} @ {f['time']} ({f['status']})")
