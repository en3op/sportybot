"""
SportyBot Admin Dashboard
Flask-based web dashboard for managing VIP users, viewing fixtures, and sending picks.
Enhanced with approval workflow and pipeline integration.
"""

import os
import json
import sqlite3
import logging
from datetime import datetime, timedelta
from pathlib import Path

import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash

from sportybet_scraper import fetch_upcoming_events, generate_daily_picks

app = Flask(__name__)
app.secret_key = os.urandom(24)


@app.template_filter("datetimeformat")
def datetimeformat(value):
    """Convert a unix timestamp to date + time format."""
    try:
        return datetime.fromtimestamp(value).strftime("%b %d, %H:%M")
    except:
        return "TBD"


@app.template_filter("dateformat")
def dateformat(value):
    """Convert a unix timestamp to full date format."""
    try:
        return datetime.fromtimestamp(value).strftime("%a, %d %b %Y")
    except:
        return "TBD"


@app.template_filter("timeformat")
def timeformat(value):
    """Convert a unix timestamp to time only."""
    try:
        return datetime.fromtimestamp(value).strftime("%H:%M")
    except:
        return "TBD"


BOT_TOKEN = os.environ.get("VIP_BOT_TOKEN", "8791071506:AAGZv4Y3GWSMQ5mnj_vH2cT3p0BWEpxOOmk")
DB_PATH = os.environ.get("DB_PATH", "vip_users.db")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
OUTPUT_DIR = Path("output")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# =============================================================================
# DATABASE HELPERS
# =============================================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vip_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            added_date TEXT,
            expiry_date TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS messages_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message_text TEXT,
            sent_count INTEGER,
            sent_date TEXT
        )
    """)
    conn.commit()
    conn.close()


# =============================================================================
# ROUTES
# =============================================================================

@app.route("/")
def dashboard():
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    total_vips = conn.execute("SELECT COUNT(*) FROM vip_users").fetchone()[0]
    active_vips = conn.execute(
        "SELECT COUNT(*) FROM vip_users WHERE expiry_date > ?", (now,)
    ).fetchone()[0]
    expired_vips = total_vips - active_vips

    today = datetime.now().strftime("%Y-%m-%d")
    msgs_today = conn.execute(
        "SELECT COALESCE(SUM(sent_count), 0) FROM messages_log WHERE sent_date LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]

    recent_msgs = conn.execute(
        "SELECT * FROM messages_log ORDER BY id DESC LIMIT 5"
    ).fetchall()

    events = fetch_upcoming_events(page_size=100, today_only=True)
    fixtures_count = len(events)

    # Check for pending pipeline output
    pending_slips = _get_pending_output()

    conn.close()

    # Pool & pipeline stats
    pool_stats = {}
    grading_stats = {}
    recent_runs = []
    accuracy_by_tier = []
    upcoming_by_date = []
    try:
        from core.pool_manager import get_pool_summary, _get_db as get_pool_db
        pool_stats = get_pool_summary()

        pool_conn = get_pool_db()
        now_str = datetime.now().isoformat()

        # Predictions by tier
        tiers = pool_conn.execute("""
            SELECT p.risk_tier, COUNT(*) as count
            FROM predictions p JOIN matches m ON p.match_id = m.match_id
            WHERE p.result = 'pending' AND m.status = 'scheduled' AND (m.expires_at IS NULL OR m.expires_at > ?)
            GROUP BY p.risk_tier
        """, (now_str,)).fetchall()
        pool_stats["predictions_by_tier"] = {r["risk_tier"]: r["count"] for r in tiers}

        # Grading
        graded = pool_conn.execute("SELECT COUNT(*) as c FROM predictions WHERE result IN ('win','loss')").fetchone()["c"]
        wins = pool_conn.execute("SELECT COUNT(*) as c FROM predictions WHERE result = 'win'").fetchone()["c"]
        pending_preds = pool_conn.execute("SELECT COUNT(*) as c FROM predictions WHERE result = 'pending'").fetchone()["c"]
        grading_stats = {
            "total_graded": graded,
            "wins": wins,
            "losses": graded - wins,
            "pending": pending_preds,
            "win_rate": round((wins / graded) * 100, 1) if graded > 0 else 0,
        }

        # Accuracy by tier
        acc_rows = pool_conn.execute(
            "SELECT * FROM accuracy_stats WHERE period LIKE '%tier%' ORDER BY accuracy DESC"
        ).fetchall()
        accuracy_by_tier = [dict(r) for r in acc_rows]

        # Upcoming by date
        upcoming_rows = pool_conn.execute("""
            SELECT DATE(match_date) as date, COUNT(*) as matches
            FROM matches WHERE status = 'scheduled' AND match_date >= ?
            GROUP BY DATE(match_date) ORDER BY match_date
        """, (datetime.now().strftime("%Y-%m-%d"),)).fetchall()
        upcoming_by_date = [dict(r) for r in upcoming_rows]

        pool_conn.close()
    except Exception:
        pass

    # Recent daily runs from history.db
    try:
        from core.history_tracker import _get_db as get_hist_db
        hist_conn = get_hist_db()
        recent_runs = [dict(r) for r in hist_conn.execute(
            "SELECT * FROM daily_runs ORDER BY id DESC LIMIT 5"
        ).fetchall()]
        hist_conn.close()
    except Exception:
        pass

    return render_template(
        "index.html",
        total_vips=total_vips,
        active_vips=active_vips,
        expired_vips=expired_vips,
        msgs_today=msgs_today,
        fixtures_count=fixtures_count,
        recent_msgs=recent_msgs,
        has_pending=pending_slips is not None,
        pool_stats=pool_stats,
        grading_stats=grading_stats,
        recent_runs=recent_runs,
        accuracy_by_tier=accuracy_by_tier,
        upcoming_by_date=upcoming_by_date,
    )


@app.route("/vip")
def vip_management():
    conn = get_db()
    search = request.args.get("search", "")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if search:
        users = conn.execute(
            "SELECT * FROM vip_users WHERE username LIKE ? OR user_id LIKE ? ORDER BY expiry_date DESC",
            (f"%{search}%", f"%{search}%"),
        ).fetchall()
    else:
        users = conn.execute(
            "SELECT * FROM vip_users ORDER BY expiry_date DESC"
        ).fetchall()

    conn.close()

    user_list = []
    for u in users:
        expiry = datetime.strptime(u["expiry_date"], "%Y-%m-%d %H:%M:%S")
        status = "active" if datetime.now() < expiry else "expired"
        user_list.append({
            "user_id": u["user_id"],
            "username": u["username"],
            "added_date": u["added_date"],
            "expiry_date": u["expiry_date"],
            "status": status,
        })

    return render_template("vip.html", users=user_list, search=search)


@app.route("/vip/add", methods=["POST"])
def add_vip():
    user_id = request.form.get("user_id", "").strip()
    username = request.form.get("username", "").strip()
    weeks = int(request.form.get("weeks", 1))

    if not user_id:
        flash("User ID is required", "danger")
        return redirect(url_for("vip_management"))

    try:
        user_id = int(user_id)
    except ValueError:
        flash("User ID must be a number", "danger")
        return redirect(url_for("vip_management"))

    conn = get_db()
    now = datetime.now()

    existing = conn.execute(
        "SELECT expiry_date FROM vip_users WHERE user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        current_expiry = datetime.strptime(existing["expiry_date"], "%Y-%m-%d %H:%M:%S")
        base = max(now, current_expiry)
    else:
        base = now

    new_expiry = base + timedelta(weeks=weeks)
    expiry_str = new_expiry.strftime("%Y-%m-%d %H:%M:%S")
    added_str = now.strftime("%Y-%m-%d %H:%M:%S")

    conn.execute(
        "INSERT OR REPLACE INTO vip_users (user_id, username, added_date, expiry_date) VALUES (?, ?, ?, ?)",
        (user_id, username or f"user_{user_id}", added_str, expiry_str),
    )
    conn.commit()
    conn.close()

    flash(f"VIP added: {user_id} (expires {expiry_str})", "success")
    return redirect(url_for("vip_management"))


@app.route("/vip/remove/<int:user_id>", methods=["POST"])
def remove_vip(user_id):
    conn = get_db()
    conn.execute("DELETE FROM vip_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    flash(f"User {user_id} removed", "success")
    return redirect(url_for("vip_management"))


@app.route("/vip/toggle/<int:user_id>", methods=["POST"])
def toggle_vip(user_id):
    conn = get_db()
    user = conn.execute(
        "SELECT expiry_date FROM vip_users WHERE user_id = ?", (user_id,)
    ).fetchone()

    if user:
        now = datetime.now()
        expiry = datetime.strptime(user["expiry_date"], "%Y-%m-%d %H:%M:%S")
        if now < expiry:
            new_expiry = now - timedelta(days=1)
        else:
            new_expiry = now + timedelta(weeks=1)

        conn.execute(
            "UPDATE vip_users SET expiry_date = ? WHERE user_id = ?",
            (new_expiry.strftime("%Y-%m-%d %H:%M:%S"), user_id),
        )
        conn.commit()
    conn.close()

    return redirect(url_for("vip_management"))


@app.route("/fixtures")
def fixtures():
    """Show only approved predictions in Fixtures & Picks."""
    from core.pool_manager import _get_db
    from datetime import datetime
    
    conn = _get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    # Get approved predictions only
    approved = conn.execute("""
        SELECT m.match_id, m.home_team, m.away_team, m.league, m.match_date,
               p.market, p.pick, p.odds, p.confidence, p.risk_tier, p.reasoning, p.approved
        FROM matches m
        JOIN predictions p ON m.match_id = p.match_id
        WHERE m.status = 'scheduled' 
          AND m.match_date >= ? 
          AND p.approved = 1
        ORDER BY m.match_date, m.league
    """, (today,)).fetchall()
    
    conn.close()
    
    # Group by date
    days_dict = {}
    for m in approved:
        date = m["match_date"][:10] if m["match_date"] else "Unknown"
        if date not in days_dict:
            days_dict[date] = {
                "date": date,
                "date_label": _format_date_label(date),
                "is_today": date == today,
                "matches": []
            }
        days_dict[date]["matches"].append({
            "match_id": m["match_id"],
            "home": m["home_team"],
            "away": m["away_team"],
            "league": m["league"],
            "time": m["match_date"][11:16] if len(m["match_date"]) > 10 else "TBD",
            "market": m["market"],
            "pick": m["pick"],
            "odds": m["odds"],
            "confidence": round(m["confidence"]) if m["confidence"] else None,
            "tier": m["risk_tier"],
            "reasoning": m["reasoning"]
        })
    
    days = [days_dict[d] for d in sorted(days_dict.keys())[:7]]
    
    return render_template("fixtures_approved.html", days=days)


@app.route("/fixtures/send", methods=["POST"])
def send_approved_picks():
    """Send all approved picks to active VIP users."""
    from core.pool_manager import _get_db
    import telebot
    from datetime import datetime
    
    conn = _get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
    approved = conn.execute("""
        SELECT m.home_team, m.away_team, m.league, m.match_date,
               p.market, p.pick, p.odds, p.confidence, p.risk_tier
        FROM matches m
        JOIN predictions p ON m.match_id = p.match_id
        WHERE m.status = 'scheduled' 
          AND m.match_date >= ? 
          AND p.approved = 1
        ORDER BY m.match_date
    """, (today,)).fetchall()
    
    if not approved:
        flash("No approved predictions to send", "warning")
        return redirect(url_for("fixtures"))
    
    # Build message
    lines = ["\U000026BD *TODAY'S APPROVED PICKS*\n"]
    for i, p in enumerate(approved, 1):
        time_str = p["match_date"][11:16] if p["match_date"] else "TBD"
        home = p["home_team"]
        away = p["away_team"]
        lines.append(f"{i}. *{home}* vs *{away}*")
        lines.append(f"   \U00002B50 {p['market']}: {p['pick']} @ {p['odds']:.2f}")
        lines.append(f"   \U0001F4CA {p['league']} | {time_str}")
        if p['confidence']:
            lines.append(f"   \U0001F3AF Confidence: {p['confidence']}%")
        lines.append("")
    
    message = "\n".join(lines)
    
    # Get active VIPs
    vips = conn.execute(
        "SELECT telegram_id FROM vip_users WHERE is_active = 1"
    ).fetchall()
    conn.close()
    
    if not vips:
        flash("No active VIP users to send to", "warning")
        return redirect(url_for("fixtures"))
    
    # Send via Telegram bot
    bot = telebot.TeleBot(BOT_TOKEN)
    
    sent_count = 0
    for vip in vips:
        try:
            bot.send_message(vip["telegram_id"], message, parse_mode="Markdown")
            sent_count += 1
        except Exception as e:
            flash(f"Failed to send to {vip['telegram_id']}: {e}", "danger")
    
    flash(f"Sent {len(approved)} picks to {sent_count} VIP users", "success")
    return redirect(url_for("fixtures"))


@app.route("/fixtures/refresh")
def refresh_fixtures():
    return redirect(url_for("fixtures"))


@app.route("/schedule")
def schedule():
    """7-day match schedule grouped by date."""
    from datetime import datetime, timedelta
    from core.pool_manager import _get_db
    
    conn = _get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    
# Get all matches for next 7 days
    matches = conn.execute("""
        SELECT m.match_id, m.home_team, m.away_team, m.league, m.match_date,
               p.market, p.pick, p.odds, p.confidence, p.risk_tier, p.approved
        FROM matches m
        LEFT JOIN predictions p ON m.match_id = p.match_id
        WHERE m.status = 'scheduled' AND m.match_date >= ?
        ORDER BY m.match_date, m.league
        """, (today,)).fetchall()

    conn.close()

    # Group by date
    days_dict = {}
    for m in matches:
        date = m["match_date"][:10] if m["match_date"] else "Unknown"
        if date not in days_dict:
            days_dict[date] = {
                "date": date,
                "date_label": _format_date_label(date),
                "is_today": date == today,
                "matches": {},
                "approved_count": 0
            }

        match_key = m["match_id"]
        if match_key not in days_dict[date]["matches"]:
            approved = m["approved"] == 1 if m["approved"] is not None else False
            if approved:
                days_dict[date]["approved_count"] += 1
            days_dict[date]["matches"][match_key] = {
                "match_id": m["match_id"],
                "home": m["home_team"],
                "away": m["away_team"],
                "league": m["league"],
                "time": m["match_date"][11:16] if len(m["match_date"]) > 10 else "TBD",
                "tier": m["risk_tier"] if m["risk_tier"] else None,
                "confidence": round(m["confidence"]) if m["confidence"] else None,
                "approved": approved,
                "best_pick": {
                    "market": m["market"],
                    "pick": m["pick"],
                    "odds": m["odds"]
                } if m["market"] else None
            }

    # Convert to list and flatten matches
    days = []
    for date in sorted(days_dict.keys())[:7]:
        day_data = days_dict[date]
        day_data["matches"] = list(day_data["matches"].values())
        days.append(day_data)

    return render_template("schedule.html", days=days)


@app.route("/schedule/prediction/<match_id>", methods=["GET", "POST", "DELETE"])
def manage_prediction(match_id):
    """Get, create, update, or delete a prediction for a match."""
    from core.pool_manager import _get_db
    import json
    
    conn = _get_db()
    
    if request.method == "GET":
        pred = conn.execute(
            "SELECT market, pick, odds, confidence, risk_tier, reasoning FROM predictions WHERE match_id = ?",
            (match_id,)
        ).fetchone()
        conn.close()
        if pred:
            return jsonify({
                "market": pred["market"],
                "pick": pred["pick"],
                "odds": pred["odds"],
                "confidence": pred["confidence"],
                "risk_tier": pred["risk_tier"],
                "reasoning": pred["reasoning"]
            })
        return jsonify({})
    
    elif request.method == "POST":
        data = request.get_json()

        existing = conn.execute(
            "SELECT id FROM predictions WHERE match_id = ?", (match_id,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE predictions SET 
                    market = ?, pick = ?, odds = ?, confidence = ?, risk_tier = ?, reasoning = ?, approved = ?, updated_at = datetime('now')
                WHERE match_id = ?
            """, (data.get("market"), data.get("pick"), data.get("odds"), 
                  data.get("confidence"), data.get("risk_tier"), data.get("reasoning"),
                  data.get("approved", 0), match_id))
        else:
            conn.execute("""
                INSERT INTO predictions (match_id, market, pick, odds, confidence, risk_tier, reasoning, source, approved)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?)
            """, (match_id, data.get("market"), data.get("pick"), data.get("odds"),
                  data.get("confidence"), data.get("risk_tier"), data.get("reasoning"),
                  data.get("approved", 0)))

        conn.commit()
        conn.close()

        return jsonify({
            "success": True,
            "prediction": {
                "market": data.get("market"),
                "pick": data.get("pick"),
                "odds": data.get("odds"),
                "confidence": data.get("confidence")
            }
        })

    elif request.method == "DELETE":
        conn.execute("DELETE FROM predictions WHERE match_id = ?", (match_id,))
        conn.commit()
        conn.close()
        return jsonify({"success": True})


@app.route("/schedule/approve/<match_id>", methods=["POST"])
def approve_prediction(match_id):
    """Approve a prediction to show in Fixtures & Picks."""
    from core.pool_manager import _get_db
    conn = _get_db()
    conn.execute("UPDATE predictions SET approved = 1 WHERE match_id = ?", (match_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


@app.route("/schedule/unapprove/<match_id>", methods=["POST"])
def unapprove_prediction(match_id):
    """Remove approval from a prediction."""
    from core.pool_manager import _get_db
    conn = _get_db()
    conn.execute("UPDATE predictions SET approved = 0 WHERE match_id = ?", (match_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})


def _format_date_label(date_str):
    """Format date as 'Monday, Mar 31'."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        return dt.strftime("%A, %b %d")
    except:
        return date_str


@app.route("/schedule/fotmob")
def refresh_from_fotmob():
    """Fetch matches from FotMob and populate prediction pool."""
    from fotmob_scraper import populate_pool_from_fotmob, populate_predictions_from_fotmob
    
    try:
        matches_stored = populate_pool_from_fotmob(max_matches=100)
        preds_stored = populate_predictions_from_fotmob(max_analyze=30)
        
        flash(f"Fetched {matches_stored} matches and generated {preds_stored} predictions from FotMob", "success")
    except Exception as e:
        flash(f"Error fetching from FotMob: {e}", "danger")
    
    return redirect(url_for("schedule"))


# =============================================================================
# PIPELINE PICKS ROUTES
# =============================================================================

@app.route("/picks")
def picks_dashboard():
    """Pipeline-generated picks with approval workflow."""
    output = _get_pending_output()
    return render_template("picks.html", output=output)


@app.route("/picks/run", methods=["POST"])
def run_pipeline():
    """Manually trigger the pipeline."""
    return _execute_pipeline()


@app.route("/picks/refresh", methods=["POST"])
def refresh_picks():
    """Refresh picks - same as run but with clear feedback."""
    return _execute_pipeline()


def _execute_pipeline():
    """Execute the pipeline and return result."""
    try:
        from core.pipeline import run_full_pipeline
        output = run_full_pipeline(today_only=True)
        _save_output(output)
        matches = output.get('summary', {}).get('qualified_matches', 0)
        safe = len(output.get('safe_slip', []))
        moderate = len(output.get('moderate_slip', []))
        high = len(output.get('high_slip', []))
        flash(f"Picks refreshed: {matches} matches | Safe:{safe} Mod:{moderate} High:{high}", "success")
    except Exception as e:
        logger.error(f"Pipeline error: {e}")
        flash(f"Pipeline error: {e}", "danger")
    return redirect(url_for("picks_dashboard"))


@app.route("/picks/approve", methods=["POST"])
def approve_picks():
    """Approve picks for VIP publishing."""
    output = _get_pending_output()
    if not output:
        flash("No pending picks to approve", "warning")
        return redirect(url_for("picks_dashboard"))

    output["status"] = "approved"
    output["admin_actions"]["approved"] = True
    _save_output(output)
    flash("Picks approved!", "success")
    return redirect(url_for("picks_dashboard"))


@app.route("/picks/reject", methods=["POST"])
def reject_picks():
    """Reject picks."""
    output = _get_pending_output()
    if output:
        output["status"] = "rejected"
        _save_output(output)
    flash("Picks rejected", "warning")
    return redirect(url_for("picks_dashboard"))


@app.route("/picks/remove/<slip_type>/<int:index>", methods=["POST"])
def remove_pick(slip_type, index):
    """Remove a specific pick from a slip."""
    output = _get_pending_output()
    if not output:
        return redirect(url_for("picks_dashboard"))

    slip = output.get(slip_type, [])
    if 0 <= index < len(slip):
        removed = slip.pop(index)
        output["admin_actions"]["removed_picks"].append(removed)
        _save_output(output)
        flash(f"Removed: {removed.get('pick', 'pick')}", "info")

    return redirect(url_for("picks_dashboard"))


@app.route("/picks/edit/<slip_type>/<int:index>", methods=["POST"])
def edit_pick(slip_type, index):
    """Edit a specific pick."""
    output = _get_pending_output()
    if not output:
        return redirect(url_for("picks_dashboard"))

    slip = output.get(slip_type, [])
    if 0 <= index < len(slip):
        new_pick = request.form.get("pick", "").strip()
        new_odds = request.form.get("odds", "").strip()

        if new_pick:
            slip[index]["pick"] = new_pick
        if new_odds:
            try:
                slip[index]["odds"] = float(new_odds)
            except ValueError:
                pass

        output["admin_actions"]["edited_picks"].append(slip[index])
        _save_output(output)
        flash(f"Pick updated", "success")

    return redirect(url_for("picks_dashboard"))


@app.route("/picks/publish", methods=["POST"])
def publish_to_vip():
    """Publish approved picks to all active VIP users."""
    output = _get_pending_output()
    if not output:
        flash("No picks to publish", "warning")
        return redirect(url_for("picks_dashboard"))

    if not output.get("admin_actions", {}).get("approved"):
        flash("Picks must be approved first", "warning")
        return redirect(url_for("picks_dashboard"))

    # Format message
    from core.pipeline import format_for_telegram
    msg = format_for_telegram(output)

    # Send to all VIPs
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vips = conn.execute(
        "SELECT user_id FROM vip_users WHERE expiry_date > ?", (now,)
    ).fetchall()

    sent_count = 0
    for vip in vips:
        try:
            r = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": vip["user_id"], "text": msg[:4096]},
                timeout=10,
            )
            if r.status_code == 200:
                sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send to {vip['user_id']}: {e}")

    conn.execute(
        "INSERT INTO messages_log (message_text, sent_count, sent_date) VALUES (?, ?, ?)",
        (msg[:500], sent_count, now),
    )
    conn.commit()
    conn.close()

    # Mark as published
    output["status"] = "published"
    output["admin_actions"]["published_to_vip"] = True
    output["admin_actions"]["published_at"] = now
    _save_output(output)

    flash(f"Published to {sent_count} VIP users", "success")
    return redirect(url_for("picks_dashboard"))


@app.route("/send/<event_id>", methods=["POST"])
def send_pick(event_id):
    """Send a specific pick to all active VIPs."""
    result = generate_daily_picks(today_only=True)
    target = None
    for p in result["top_10"]:
        if p.get("event_id") == event_id:
            target = p
            break

    if not target:
        flash("Pick not found", "danger")
        return redirect(url_for("fixtures"))

    ts = "TBD"
    if target.get("start_time_ms"):
        try:
            ts = datetime.fromtimestamp(target["start_time_ms"] / 1000).strftime("%H:%M")
        except Exception:
            pass
    msg = (
        f"PICK ALERT\n"
        f"{'=' * 24}\n"
        f"{target['home']} vs {target['away']}\n"
        f"{target['league']} | {ts}\n"
        f"{target['market']}: {target['pick']} @ {target['odds']:.2f}\n"
        f"Implied: {target['implied']}% | Tier {target['tier']}"
    )

    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vips = conn.execute(
        "SELECT user_id FROM vip_users WHERE expiry_date > ?", (now,)
    ).fetchall()

    sent_count = 0
    for vip in vips:
        try:
            r = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": vip["user_id"], "text": msg},
                timeout=10,
            )
            if r.status_code == 200:
                sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send to {vip['user_id']}: {e}")

    conn.execute(
        "INSERT INTO messages_log (message_text, sent_count, sent_date) VALUES (?, ?, ?)",
        (msg[:500], sent_count, now),
    )
    conn.commit()
    conn.close()

    flash(f"Pick sent to {sent_count} VIP users", "success")
    return redirect(url_for("fixtures"))


def _format_slips_message(top_10, slips):
    """Format the 3 slips into a Telegram-ready message."""
    now_str = datetime.now().strftime("%a, %b %d, %Y")
    lines = [f"DAILY SLIPS - {now_str}", "=" * 32, "", "TOP 10 PICKS", "-" * 32]

    for i, p in enumerate(top_10, 1):
        ts = "TBD"
        if p.get("start_time_ms"):
            try:
                ts = datetime.fromtimestamp(p["start_time_ms"] / 1000).strftime("%H:%M")
            except Exception:
                pass
        lines.append(f"{i}. {p['home']} vs {p['away']}")
        lines.append(f"   {p['league']} | {ts}")
        lines.append(f"   {p['market']}: {p['pick']} @ {p['odds']:.2f}")
        lines.append(f"   Implied: {p['implied']}% | Tier {p['tier']}")
        lines.append("")

    for key, label in [("slip_a", "SLIP A"), ("slip_b", "SLIP B"), ("slip_c", "SLIP C")]:
        slip = slips[key]
        combined = slips["combined"][key[-1]]
        risk = "SAFE" if key == "slip_a" else "MODERATE" if key == "slip_b" else "HIGH"
        lines.append("=" * 32)
        lines.append(f"{label} ({combined:.1f}x) - {risk}")
        for i, p in enumerate(slip, 1):
            lines.append(f"  {i}. {p['home']} vs {p['away']}")
            lines.append(f"     {p['market']}: {p['pick']} @ {p['odds']:.2f} | Tier {p['tier']}")
        lines.append("")

    return "\n".join(lines)


@app.route("/send-all", methods=["POST"])
def send_all_picks():
    """Generate and send all 3 slips to active VIPs."""
    result = generate_daily_picks(today_only=True)
    top_10 = result["top_10"]
    slips = result["slips"]

    if not top_10:
        flash("No picks available", "warning")
        return redirect(url_for("fixtures"))

    msg = _format_slips_message(top_10, slips)

    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    vips = conn.execute(
        "SELECT user_id FROM vip_users WHERE expiry_date > ?", (now,)
    ).fetchall()

    sent_count = 0
    for vip in vips:
        try:
            r = requests.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": vip["user_id"], "text": msg},
                timeout=10,
            )
            if r.status_code == 200:
                sent_count += 1
        except Exception as e:
            logger.error(f"Failed to send to {vip['user_id']}: {e}")

    conn.execute(
        "INSERT INTO messages_log (message_text, sent_count, sent_date) VALUES (?, ?, ?)",
        (msg[:500], sent_count, now),
    )
    conn.commit()
    conn.close()

    flash(f"3 slips sent to {sent_count} VIP users", "success")
    return redirect(url_for("fixtures"))


@app.route("/settings")
def settings():
    return render_template("settings.html", bot_token=BOT_TOKEN[:20] + "...", db_path=DB_PATH)


@app.route("/api/stats")
def api_stats():
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today = datetime.now().strftime("%Y-%m-%d")

    total_vips = conn.execute("SELECT COUNT(*) FROM vip_users").fetchone()[0]
    active_vips = conn.execute(
        "SELECT COUNT(*) FROM vip_users WHERE expiry_date > ?", (now,)
    ).fetchone()[0]
    msgs_today = conn.execute(
        "SELECT COALESCE(SUM(sent_count), 0) FROM messages_log WHERE sent_date LIKE ?",
        (f"{today}%",),
    ).fetchone()[0]

    conn.close()
    return jsonify({
        "total_vips": total_vips,
        "active_vips": active_vips,
        "msgs_today": msgs_today,
    })


@app.route("/api/picks")
def api_picks():
    """API endpoint for current picks JSON."""
    output = _get_pending_output()
    if not output:
        return jsonify({"error": "No picks available"}), 404
    return jsonify(output)


# =============================================================================
# HELPERS
# =============================================================================

def _get_pending_output():
    """Load the latest pipeline output."""
    latest = OUTPUT_DIR / "latest.json"
    if latest.exists():
        try:
            with open(latest, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _save_output(output):
    """Save pipeline output."""
    OUTPUT_DIR.mkdir(exist_ok=True)
    date_str = output.get("date", datetime.now().strftime("%Y-%m-%d"))

    filepath = OUTPUT_DIR / f"daily_{date_str}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)

    latest = OUTPUT_DIR / "latest.json"
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)


# =============================================================================
# N8N WEBHOOK ENDPOINTS
# =============================================================================

N8N_SECRET = "sportybot-n8n-2026"  # Change this to a secure value


def _verify_n8n(request):
    """Verify n8n webhook secret."""
    token = request.headers.get("X-N8N-Secret", "") or request.args.get("secret", "")
    return token == N8N_SECRET


@app.route("/api/n8n/weekly", methods=["POST"])
def n8n_weekly():
    """n8n webhook: trigger weekly prediction pool cycle."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.weekly_runner import run_weekly_cycle
        result = run_weekly_cycle()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error(f"n8n weekly error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/n8n/refresh", methods=["POST"])
def n8n_refresh():
    """n8n webhook: trigger daily odds refresh."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.daily_refresh import run_daily_refresh
        result = run_daily_refresh()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error(f"n8n refresh error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/n8n/grade", methods=["POST"])
def n8n_grade():
    """n8n webhook: grade finished matches."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.grader import grade_finished_matches
        result = grade_finished_matches()
        return jsonify({"status": "ok", **result})
    except Exception as e:
        logger.error(f"n8n grade error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/n8n/pool-summary", methods=["GET"])
def n8n_pool_summary():
    """n8n webhook: get pool summary."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.pool_manager import get_pool_summary
        return jsonify(get_pool_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/n8n/top-picks", methods=["GET"])
def n8n_top_picks():
    """n8n webhook: get top predictions."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.pool_manager import get_top_predictions
        min_conf = float(request.args.get("min_confidence", 80))
        limit = int(request.args.get("limit", 10))
        picks = get_top_predictions(min_confidence=min_conf, max_results=limit)
        # Remove non-serializable fields
        for p in picks:
            p.pop("source_data", None)
        return jsonify(picks)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/n8n/push-telegram", methods=["POST"])
def n8n_push_telegram():
    """n8n webhook: push picks to Telegram VIPs."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.pool_manager import get_top_predictions
        from core.pool_slip_generator import generate_slips_from_matches, format_slip_telegram

        picks = get_top_predictions(min_confidence=70, max_results=20)
        if not picks:
            return jsonify({"status": "ok", "sent": 0, "message": "No picks available"})

        # Group by match for slip generation
        by_match = {}
        for p in picks:
            mid = p.get("match_id", "")
            if mid not in by_match:
                by_match[mid] = {
                    "pool_match": {
                        "home_team": p["home_team"],
                        "away_team": p["away_team"],
                        "league": p.get("league", ""),
                        "match_date": p.get("match_date", ""),
                        "match_id": mid,
                    },
                    "predictions": [],
                    "research": {},
                }
            by_match[mid]["predictions"].append(p)

        matched_data = list(by_match.values())
        slips = generate_slips_from_matches(matched_data)

        # Format message
        msg_parts = []
        for label, key, risk in [("SAFE", "safe_slip", "LOW RISK"), ("MEDIUM", "medium_slip", "MEDIUM RISK"), ("RISKY", "risky_slip", "HIGH RISK")]:
            formatted = format_slip_telegram(slips[key], label, risk)
            if formatted and "No qualifying" not in formatted:
                msg_parts.append(formatted)

        full_msg = "\n\n".join(msg_parts)
        if not full_msg:
            return jsonify({"status": "ok", "sent": 0})

        # Send to VIPs
        conn = get_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        vips = conn.execute("SELECT user_id FROM vip_users WHERE expiry_date > ?", (now,)).fetchall()

        sent = 0
        for vip in vips:
            try:
                requests.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json={"chat_id": vip["user_id"], "text": full_msg[:4096]},
                    timeout=10,
                )
                sent += 1
            except Exception:
                pass

        conn.close()
        return jsonify({"status": "ok", "sent": sent})

    except Exception as e:
        logger.error(f"n8n push error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/api/n8n/status", methods=["GET"])
def n8n_status():
    """n8n webhook: full system status for monitoring."""
    if not _verify_n8n(request):
        return jsonify({"error": "unauthorized"}), 401

    try:
        from core.pool_manager import _get_db as get_pool_db, get_pool_summary
        from core.history_tracker import _get_db as get_hist_db

        status = {"status": "ok", "timestamp": datetime.now().isoformat()}

        # Pool stats
        try:
            status["pool"] = get_pool_summary()
        except Exception:
            status["pool"] = {"error": "pool db not initialized"}

        # Prediction breakdown by tier
        try:
            pool_conn = get_pool_db()
            now = datetime.now().isoformat()
            tiers = pool_conn.execute("""
                SELECT p.risk_tier, COUNT(*) as count
                FROM predictions p JOIN matches m ON p.match_id = m.match_id
                WHERE p.result = 'pending' AND m.status = 'scheduled' AND (m.expires_at IS NULL OR m.expires_at > ?)
                GROUP BY p.risk_tier
            """, (now,)).fetchall()
            status["pool"]["predictions_by_tier"] = {r["risk_tier"]: r["count"] for r in tiers}
            pool_conn.close()
        except Exception:
            pass

        # Recent daily runs
        try:
            hist_conn = get_hist_db()
            runs = hist_conn.execute(
                "SELECT * FROM daily_runs ORDER BY id DESC LIMIT 5"
            ).fetchall()
            status["recent_runs"] = [dict(r) for r in runs]
            hist_conn.close()
        except Exception:
            status["recent_runs"] = []

        # Accuracy stats
        try:
            pool_conn = get_pool_db()
            acc = pool_conn.execute(
                "SELECT * FROM accuracy_stats ORDER BY accuracy DESC LIMIT 10"
            ).fetchall()
            status["accuracy"] = [dict(r) for r in acc]
            pool_conn.close()
        except Exception:
            status["accuracy"] = []

        # Upcoming matches by date
        try:
            pool_conn = get_pool_db()
            upcoming = pool_conn.execute("""
                SELECT DATE(match_date) as date, COUNT(*) as matches
                FROM matches WHERE status = 'scheduled' AND match_date >= ?
                GROUP BY DATE(match_date) ORDER BY match_date
            """, (datetime.now().strftime("%Y-%m-%d"),)).fetchall()
            status["upcoming_by_date"] = [dict(r) for r in upcoming]
            pool_conn.close()
        except Exception:
            status["upcoming_by_date"] = []

        # Grading stats
        try:
            pool_conn = get_pool_db()
            graded = pool_conn.execute(
                "SELECT COUNT(*) as c FROM predictions WHERE result IN ('win','loss')"
            ).fetchone()["c"]
            wins = pool_conn.execute(
                "SELECT COUNT(*) as c FROM predictions WHERE result = 'win'"
            ).fetchone()["c"]
            pending = pool_conn.execute(
                "SELECT COUNT(*) as c FROM predictions WHERE result = 'pending'"
            ).fetchone()["c"]
            void = pool_conn.execute(
                "SELECT COUNT(*) as c FROM predictions WHERE result = 'void'"
            ).fetchone()["c"]
            pool_conn.close()
            status["grading"] = {
                "total_graded": graded,
                "wins": wins,
                "losses": graded - wins,
                "pending": pending,
                "void": void,
                "win_rate": round((wins / graded) * 100, 1) if graded > 0 else 0,
            }
        except Exception:
            status["grading"] = {"error": "unavailable"}

        return jsonify(status)
    except Exception as e:
        logger.error(f"n8n status error: {e}")
        return jsonify({"status": "error", "error": str(e)}), 500


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import os
    init_db()
    port = int(os.environ.get("PORT", 5000))
    print(f"SportyBot Dashboard running on port {port}")
    app.run(debug=False, host="0.0.0.0", port=port)
