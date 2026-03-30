"""
Daily Automation Runner
=======================
Runs the full pipeline on a schedule.
Can be run as a standalone script or imported.

Usage:
    python runner.py              # Run once now
    python runner.py --schedule   # Run daily at configured time
    python runner.py --cron       # Set up system cron job
"""

import sys
import os
import json
import time
import logging
import argparse
from datetime import datetime
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pipeline import run_full_pipeline, format_for_telegram

logger = logging.getLogger(__name__)

# Configuration
CONFIG = {
    "run_hour": 8,          # Run at 8 AM daily
    "run_minute": 0,
    "min_score": 60.0,
    "max_matches": 25,
    "output_dir": "output",
    "notify_admin": True,
}


def run_daily():
    """Execute the daily pipeline run."""
    logger.info(f"Daily run triggered at {datetime.now()}")

    try:
        output = run_full_pipeline(
            today_only=True,
            min_score=CONFIG["min_score"],
            max_matches=CONFIG["max_matches"],
        )

        # Save output to file
        _save_output(output)

        # Log summary
        summary = output.get("summary", {})
        logger.info(f"Daily run complete: {summary.get('qualified_matches', 0)} matches, "
                     f"{output.get('summary', {}).get('total_picks_generated', 0)} picks")

        return output

    except Exception as e:
        logger.error(f"Daily run failed: {e}", exc_info=True)
        return None


def run_scheduler():
    """Run the pipeline daily at the configured time."""
    try:
        import schedule
    except ImportError:
        logger.error("Install 'schedule' package: pip install schedule")
        print("Error: pip install schedule")
        return

    schedule.every().day.at(f"{CONFIG['run_hour']:02d}:{CONFIG['run_minute']:02d}").do(run_daily)

    logger.info(f"Scheduler started. Will run daily at {CONFIG['run_hour']:02d}:{CONFIG['run_minute']:02d}")
    logger.info("Press Ctrl+C to stop.")

    # Run once immediately
    run_daily()

    while True:
        schedule.run_pending()
        time.sleep(60)


def setup_cron():
    """Generate cron setup instructions."""
    script_path = os.path.abspath(__file__)
    python_path = sys.executable
    project_dir = str(Path(__file__).parent.parent)

    cron_line = f"{CONFIG['run_minute']} {CONFIG['run_hour']} * * * cd {project_dir} && {python_path} {script_path} >> {project_dir}/output/cron.log 2>&1"

    print("\nCron Job Setup")
    print("=" * 40)
    print(f"\nAdd this line to your crontab (crontab -e):\n")
    print(f"  {cron_line}")
    print(f"\nOr on Windows, use Task Scheduler to run:")
    print(f"  {python_path} {script_path}")
    print(f"  Daily at {CONFIG['run_hour']:02d}:{CONFIG['run_minute']:02d}")


def _save_output(output: dict):
    """Save output to JSON file."""
    output_dir = Path(__file__).parent.parent / CONFIG["output_dir"]
    output_dir.mkdir(exist_ok=True)

    date_str = datetime.now().strftime("%Y-%m-%d")
    filepath = output_dir / f"daily_{date_str}.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info(f"Output saved to {filepath}")

    # Also save as latest.json
    latest = output_dir / "latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser(description="SportyBot Daily Runner")
    parser.add_argument("--schedule", action="store_true", help="Run on a daily schedule")
    parser.add_argument("--cron", action="store_true", help="Show cron setup instructions")
    parser.add_argument("--min-score", type=float, default=60.0, help="Minimum score threshold")
    parser.add_argument("--max-matches", type=int, default=25, help="Max matches to rank")
    parser.add_argument("--weekly", action="store_true", help="Run weekly prediction pool cycle")
    parser.add_argument("--refresh", action="store_true", help="Run daily odds refresh")
    parser.add_argument("--grade", action="store_true", help="Grade finished matches")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("output/runner.log", mode="a"),
        ],
    )

    CONFIG["min_score"] = args.min_score
    CONFIG["max_matches"] = args.max_matches

    if args.cron:
        setup_cron()
    elif args.weekly:
        from core.weekly_runner import run_weekly_cycle
        result = run_weekly_cycle()
        print(f"Weekly cycle complete: {result}")
    elif args.refresh:
        from core.daily_refresh import run_daily_refresh
        result = run_daily_refresh()
        print(f"Daily refresh complete: {result}")
    elif args.grade:
        from core.grader import grade_finished_matches
        result = grade_finished_matches()
        print(f"Grading complete: {result}")
    elif args.schedule:
        run_scheduler()
    else:
        output = run_daily()
        if output:
            print(format_for_telegram(output))


if __name__ == "__main__":
    main()
