"""
Main Pipeline Orchestrator
==========================
Runs the full pipeline:
  Scrape -> Normalize -> Score -> Rank -> Generate Slips -> Store -> Output
"""

import logging
import json
from datetime import datetime
from typing import Optional
from pathlib import Path

from core.scraper import fetch_comprehensive_data, scrape_flashscore_fixtures
from core.normalizer import normalize_all, count_total_markets
from core.scoring_engine import calculate_all_scores
from core.ai_agent import research_and_score_events
from core.ranker import rank_matches, get_global_pick_pool, filter_diversified_picks, get_ranking_summary
from core.slip_generator import generate_all_slips, format_slip_for_display, _combined_odds
from core.history_tracker import init_history_db, store_daily_run, adjust_weights_based_on_history

logger = logging.getLogger(__name__)


def _fetch_all_events(today_only: bool = True, max_pages: int = 10) -> list[dict]:
    """Fetch events using the working SportyBet API scraper.

    Adapts the output format to match what the pipeline expects.
    Falls back to non-today events if today has none.
    Fetches multiple pages to get all available matches.
    """
    import sys
    import os
    import time
    parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from sportybet_scraper import fetch_upcoming_events

    all_events = []
    seen_ids = set()

    # Fetch multiple pages
    for page in range(1, max_pages + 1):
        raw = fetch_upcoming_events(page_size=100, page_num=page, today_only=False)
        if not raw:
            break

        # Deduplicate by event ID
        new_events = []
        for ev in raw:
            ev_id = ev.get("id") or f"{ev.get('home', '')}_{ev.get('away', '')}"
            if ev_id not in seen_ids:
                seen_ids.add(ev_id)
                new_events.append(ev)

        if new_events:
            all_events.extend(new_events)
            logger.info(f"Fetched page {page}: {len(new_events)} new events (total: {len(all_events)})")

        # Rate limit between pages
        time.sleep(0.3)

    if not all_events:
        return []

    for ev in all_events:
        ev["market_count"] = len(ev.get("markets", {}))

    logger.info(f"Total unique events fetched: {len(all_events)}")
    return all_events


def run_full_pipeline(today_only: bool = True, min_score: float = 60.0, max_matches: int = 25, use_sofascore: bool = True) -> dict:
    """Execute the complete betting intelligence pipeline.

    Args:
        today_only: Only process today's matches
        min_score: Minimum consistency score threshold
        max_matches: Maximum matches to include in ranking
        use_sofascore: Whether to fetch form data from SofaScore (default True)

    Returns:
        Complete output dict with all data ready for admin dashboard.
    """
    date_str = datetime.now().strftime("%Y-%m-%d")
    logger.info(f"=== Pipeline started for {date_str} ===")

    # Initialize history DB
    init_history_db()

    # Step 1: Data Collection (use working SportyBet API scraper)
    logger.info("[1/6] Scraping match data...")
    raw_events = _fetch_all_events(today_only=today_only)
    logger.info(f"  Collected {len(raw_events)} events from SportyBet API")

    # Step 2: Data Normalization
    logger.info("[2/6] Normalizing data...")
    normalized = normalize_all(raw_events)
    market_stats = count_total_markets(normalized)
    logger.info(f"  Normalized: {market_stats['total_events']} events, "
                f"avg {market_stats['avg_markets_per_event']} markets/event")
    logger.info(f"  Reliability: {market_stats['reliability_breakdown']}")

    # Step 3: AI Scoring
    logger.info("[3/6] Running consistency scoring engine...")
    scored = calculate_all_scores(normalized)
    logger.info(f"  Scored {len(scored)} events with picks")

    # Step 3.5: AI Research Agent - Expert Football Analysis
    logger.info("[3.5/6] Running AI Research Agent (expert football analysis)...")
    expert_reviewed = research_and_score_events(scored, use_sofascore=use_sofascore)
    logger.info(f" Expert agent approved {len(expert_reviewed)} events")

    # Step 4: Match Ranking
    logger.info("[4/6] Ranking matches...")
    ranked = rank_matches(expert_reviewed, min_score=min_score, max_matches=max_matches)
    ranking_summary = get_ranking_summary(ranked)
    logger.info(f"  {ranking_summary['total_matches']} matches qualified (score >= {min_score})")

    # Step 5: Slip Generation
    logger.info("[5/6] Generating slips...")
    global_picks = get_global_pick_pool(ranked)
    diversified = filter_diversified_picks(global_picks)
    slips = generate_all_slips(diversified)
    logger.info(f"  Generated {len(slips['safe_slip'])} safe, "
                f"{len(slips['moderate_slip'])} moderate, "
                f"{len(slips['high_slip'])} high picks")

    # Step 6: Build output + Store
    logger.info("[6/6] Building output and storing...")
    output = build_admin_output(
        date_str=date_str,
        ranked_events=ranked,
        global_picks=diversified,
        slips=slips,
        market_stats=market_stats,
        ranking_summary=ranking_summary,
    )

    # Store in history
    run_id = store_daily_run(output)
    output["run_id"] = run_id

    # Save to file for dashboard
    _save_pipeline_output(output)

    # Self-learning weight adjustment
    adjust_weights_based_on_history()

    logger.info(f"=== Pipeline complete. Run #{run_id} ===")
    return output


def _save_pipeline_output(output: dict):
    """Save pipeline output to JSON files for the dashboard."""
    output_dir = Path(__file__).parent.parent / "output"
    output_dir.mkdir(exist_ok=True)

    date_str = output.get("date", datetime.now().strftime("%Y-%m-%d"))

    filepath = output_dir / f"daily_{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    latest = output_dir / "latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Output saved to {filepath}")


def build_admin_output(
    date_str: str,
    ranked_events: list[dict],
    global_picks: list[dict],
    slips: dict,
    market_stats: dict,
    ranking_summary: dict,
) -> dict:
    """Build the structured admin dashboard output."""

    # Format top matches for display
    top_matches = []
    for event in ranked_events:
        top_picks = event.get("scored_picks", [])
        if top_picks:
            expert = event.get("expert_analysis", {})
            top_matches.append({
                "match": f"{event['home']} vs {event['away']}",
                "home": event["home"],
                "away": event["away"],
                "league": event["league"],
                "start_time_ms": event.get("start_time_ms", 0),
                "rank": event.get("rank", 0),
                "best_score": event.get("best_score", 0),
                "reliability": event.get("reliability", "medium"),
                "top_picks": [
                    {
                        "market": p["market"],
                        "pick": p["pick"],
                        "odds": p["odds"],
                        "consistency_score": p.get("consistency_score", 0),
                        "expert_confidence": p.get("expert_confidence", 0),
                        "tier": p["tier"],
                        "reasoning": p.get("reasoning", ""),
                        "expert_reasoning": p.get("expert_reasoning", ""),
                    }
                    for p in top_picks
                ],
        "market_count": event.get("market_count", len(event.get("markets", {}))),
        "expert_analysis": {
            "tier": expert.get("tier", "C") if isinstance(expert, dict) else "C",
            "red_flags": expert.get("red_flags", []) if isinstance(expert, dict) else [],
            "boost_factors": expert.get("boost_factors", []) if isinstance(expert, dict) else [],
            "reasoning": expert.get("reasoning", "") if isinstance(expert, dict) else "",
        },
    })

    # Format slips with metadata
    def _format_slip(picks):
        return [
            {
                "match": f"{p.get('home', '')} vs {p.get('away', '')}",
                "home": p.get("home", ""),
                "away": p.get("away", ""),
                "league": p.get("league", ""),
                "market": p.get("market", ""),
                "pick": p.get("pick", ""),
                "odds": p.get("odds", 0),
                "consistency_score": p.get("consistency_score", 0),
                "expert_confidence": p.get("expert_confidence", 0),
                "tier": p.get("tier", ""),
                "reasoning": p.get("reasoning", ""),
                "expert_reasoning": p.get("expert_reasoning", ""),
                "start_time_ms": p.get("start_time_ms", 0),
            }
            for p in picks
        ]

    return {
        "date": date_str,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "pending_approval",

        "summary": {
            "total_events_scraped": market_stats.get("total_events", 0),
            "qualified_matches": ranking_summary.get("total_matches", 0),
            "total_picks_generated": len(global_picks),
            "score_range": ranking_summary.get("score_range", "N/A"),
            "avg_score": ranking_summary.get("avg_score", 0),
            "leagues_covered": ranking_summary.get("leagues", []),
            "reliability_breakdown": ranking_summary.get("reliability_breakdown", {}),
        },

        "top_matches": top_matches,

        "safe_slip": _format_slip(slips.get("safe_slip", [])),
        "moderate_slip": _format_slip(slips.get("moderate_slip", [])),
        "high_slip": _format_slip(slips.get("high_slip", [])),

        "metadata": {
            "safe_combined_odds": slips.get("metadata", {}).get("safe_combined_odds", 0),
            "moderate_combined_odds": slips.get("metadata", {}).get("moderate_combined_odds", 0),
            "high_combined_odds": slips.get("metadata", {}).get("high_combined_odds", 0),
        },

        "admin_actions": {
            "approved": False,
            "edited_picks": [],
            "removed_picks": [],
            "published_to_vip": False,
            "published_at": None,
        },
    }


def format_for_telegram(output: dict) -> str:
    """Format the full output for Telegram publishing."""
    date_str = output.get("date", "Today")
    summary = output.get("summary", {})
    top_matches = output.get("top_matches", [])

    lines = [
        f"DAILY PICKS - {date_str}",
        "=" * 30,
        "",
        f"Matches analyzed: {summary.get('total_events_scraped', 0)}",
        f"Qualified: {summary.get('qualified_matches', 0)} | Score range: {summary.get('score_range', 'N/A')}",
        "",
    ]

    # Top matches
    if top_matches:
        lines.append("TOP MATCHES (AI Agent Reviewed)")
        lines.append("-" * 30)
        for i, m in enumerate(top_matches[:10], 1):
            ts = ""
            if m.get("start_time_ms"):
                try:
                    ts = datetime.fromtimestamp(m["start_time_ms"] / 1000).strftime("%H:%M")
                except Exception:
                    pass

            lines.append(f"{i}. {m['match']}")
            lines.append(f"   {m['league']} | {ts} | Expert: {m['best_score']:.1f}")

            for pick in m.get("top_picks", [])[:1]:
                exp_conf = pick.get("expert_confidence", 0)
                lines.append(f"   {pick['market']}: {pick['pick']} @ {pick['odds']:.2f} | Confidence: {exp_conf:.0f}")
                if pick.get("expert_reasoning"):
                    lines.append(f"   Analysis: {pick['expert_reasoning']}")
            lines.append("")

    # Slips
    for slip_key, label, risk in [
        ("safe_slip", "SAFE SLIP", "LOW RISK"),
        ("moderate_slip", "MODERATE SLIP", "MEDIUM RISK"),
        ("high_slip", "HIGH SLIP", "HIGH RISK"),
    ]:
        slip = output.get(slip_key, [])
        odds_key = f"{slip_key.replace('_slip', '')}_combined_odds"
        combined = output.get("metadata", {}).get(odds_key, 0)

        if slip:
            lines.append("=" * 30)
            lines.append(f"{label} ({combined:.2f}x) - {risk}")
            lines.append("-" * 30)
            for i, p in enumerate(slip, 1):
                exp = p.get("expert_confidence", 0)
                lines.append(f"  {i}. {p['match']}")
                lines.append(f"     {p['market']}: {p['pick']} @ {p['odds']:.2f}")
                lines.append(f"     Consistency: {p['consistency_score']:.1f} | Expert: {exp:.0f} | Tier {p['tier']}")
                if p.get("expert_reasoning"):
                    lines.append(f"     {p['expert_reasoning']}")
                lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    result = run_full_pipeline()
    print(format_for_telegram(result))
