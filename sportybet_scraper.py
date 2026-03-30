# Sportybet API scraper with multi-market analysis engine.
import time, logging, requests, functools
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.sportybet.com/ng/sport/football",
    "clientid": "web", "operid": "2", "Accept-Language": "en", "Platform": "web",
}
BASE_URL = "https://www.sportybet.com/api/ng/factsCenter"


def fetch_upcoming_events(page_size=100, page_num=1, today_only=False):
    ts = int(time.time() * 1000)
    try:
        params = {
            "sportId": "sr:sport:1", "marketId": "1,18,10,29,11,26,36,14,60100",
            "pageSize": str(page_size), "pageNum": str(page_num), "option": "1", "_t": ts,
        }
        if today_only:
            params["todayGames"] = "true"
        r = requests.get(f"{BASE_URL}/pcUpcomingEvents", headers=HEADERS, params=params, timeout=15)
        data = r.json()
        if str(data.get("bizCode", "")) != "10000":
            return []
        events = []
        for t in data.get("data", {}).get("tournaments", []):
            league_name = t.get("name", "Unknown")
            for e in t.get("events", []):
                if not isinstance(e, dict):
                    continue
                markets = {}
                for m in e.get("markets", []):
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
                            outcomes[o.get("desc", "")] = float(o.get("odds", 0))
                        except Exception:
                            pass
                    if outcomes:
                        markets[key] = outcomes
                events.append({
                    "event_id": e.get("eventId", ""), "game_id": e.get("gameId", ""),
                    "league": league_name, "home": e.get("homeTeamName", ""),
                    "away": e.get("awayTeamName", ""), "start_time_ms": e.get("estimateStartTime", 0),
                    "markets": markets,
                })
        logger.info(f"Fetched {len(events)} events")
        if today_only:
            now = datetime.now()
            ts_s = int(now.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            ts_e = int((now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)).timestamp() * 1000)
            events = [e for e in events if ts_s <= e.get("start_time_ms", 0) < ts_e]
            logger.info(f"Filtered to {len(events)} today")
        return events
    except Exception as ex:
        logger.error(f"API error: {ex}")
        return []


def implied_prob(odds_list):
    raw = [1.0 / o if o > 0 else 0 for o in odds_list]
    total = sum(raw)
    if total == 0:
        return [0] * len(odds_list)
    return [r / total * 100 for r in raw]


def analyze_all_markets(event):
    home, away, league, markets = event["home"], event["away"], event["league"], event["markets"]
    plays = []

    # 1X2
    ox = markets.get("1X2", {})
    h, d, a = ox.get("Home", 0), ox.get("Draw", 0), ox.get("Away", 0)
    if h and d and a:
        probs = implied_prob([h, d, a])
        for i, (label, short, odds) in enumerate([
            (f"{home} Win (1)", "1", h), ("Draw (X)", "X", d), (f"{away} Win (2)", "2", a)
        ]):
            if probs[i] >= 55 and odds >= 1.20:
                tier = "A" if probs[i] >= 70 else ("B+" if probs[i] >= 60 else "B")
                plays.append({"market": "1X2", "pick": label, "pick_short": short, "odds": odds,
                    "implied": round(probs[i], 1), "tier": tier, "score": round(probs[i] * odds / 100, 2)})

    # BTTS
    gg_ng = markets.get("GG/NG", {})
    gg, ng = gg_ng.get("GG", 0), gg_ng.get("NG", 0)
    if gg and ng:
        probs = implied_prob([gg, ng])
        if probs[0] >= 55 and gg >= 1.30:
            tier = "A" if probs[0] >= 70 else ("B+" if probs[0] >= 60 else "B")
            plays.append({"market": "BTTS", "pick": "Both Teams Score (GG)", "pick_short": "GG",
                "odds": gg, "implied": round(probs[0], 1), "tier": tier, "score": round(probs[0] * gg / 100, 2)})
        if probs[1] >= 55 and ng >= 1.30:
            tier = "A" if probs[1] >= 70 else ("B+" if probs[1] >= 60 else "B")
            plays.append({"market": "BTTS", "pick": "No BTTS (NG)", "pick_short": "NG",
                "odds": ng, "implied": round(probs[1], 1), "tier": tier, "score": round(probs[1] * ng / 100, 2)})

    # Over/Under
    for line in ["0.5", "1.5", "2.5", "3.5", "4.5"]:
        ou = markets.get(f"Over/Under(total={line})", {})
        over, under = ou.get("Over", 0), ou.get("Under", 0)
        if over and under:
            probs = implied_prob([over, under])
            if probs[0] >= 60 and over >= 1.15:
                tier = "A" if probs[0] >= 80 else ("B+" if probs[0] >= 65 else "B")
                plays.append({"market": "Goals", "pick": f"Over {line} Goals", "pick_short": f"O{line}",
                    "odds": over, "implied": round(probs[0], 1), "tier": tier, "score": round(probs[0] * over / 100, 2)})
            if probs[1] >= 60 and under >= 1.15:
                tier = "A" if probs[1] >= 80 else ("B+" if probs[1] >= 65 else "B")
                plays.append({"market": "Goals", "pick": f"Under {line} Goals", "pick_short": f"U{line}",
                    "odds": under, "implied": round(probs[1], 1), "tier": tier, "score": round(probs[1] * under / 100, 2)})

    # Handicap
    for hcp in ["0:1", "0:2", "0:3", "1:0", "2:0", "3:0"]:
        hcp_data = markets.get(f"Handicap {hcp}(hcp={hcp})", {})
        for outcome, odds_val in hcp_data.items():
            if odds_val and odds_val > 0:
                prob = 100 / odds_val
                if prob >= 50 and odds_val >= 1.30:
                    plays.append({"market": "Handicap", "pick": f"HCP {hcp} {outcome}",
                        "pick_short": f"H{hcp}{outcome}", "odds": odds_val, "implied": round(prob, 1),
                        "tier": "B+", "score": round(prob * odds_val / 100, 2)})

    # Double Chance
    dc = markets.get("Double Chance", {})
    dc_labels = {"1X": f"{home} or Draw", "12": f"{home} or {away}", "X2": f"Draw or {away}"}
    for outcome, odds_val in dc.items():
        if odds_val and odds_val > 0:
            prob = 100 / odds_val
            if prob >= 65 and odds_val >= 1.15:
                tier = "A" if prob >= 80 else "B+"
                plays.append({"market": "Double Chance", "pick": dc_labels.get(outcome, outcome),
                    "pick_short": outcome, "odds": odds_val, "implied": round(prob, 1), "tier": tier,
                    "score": round(prob * odds_val / 100, 2)})

    # DNB
    dnb = markets.get("Draw No Bet", {})
    for outcome, odds_val in dnb.items():
        if odds_val and odds_val > 0:
            prob = 100 / odds_val
            label = f"{home} DNB" if outcome == "1" else f"{away} DNB"
            if prob >= 55 and odds_val >= 1.25:
                tier = "A" if prob >= 70 else "B+"
                plays.append({"market": "DNB", "pick": label, "pick_short": f"DNB{outcome}",
                    "odds": odds_val, "implied": round(prob, 1), "tier": tier, "score": round(prob * odds_val / 100, 2)})

    plays.sort(key=lambda p: p["score"], reverse=True)
    return {"event_id": event.get("event_id", ""), "league": league, "home": home, "away": away,
            "start_time_ms": event.get("start_time_ms", 0), "markets": markets, "plays": plays}


def analyze_all_markets_full(event):
    """Return ALL available plays from every market — no confidence thresholds.

    Used by the slip builder to pick the best market per game per tier.
    """
    home, away, league, markets = event["home"], event["away"], event["league"], event["markets"]
    plays = []

    # 1X2
    ox = markets.get("1X2", {})
    h, d, a = ox.get("Home", 0), ox.get("Draw", 0), ox.get("Away", 0)
    if h and d and a:
        probs = implied_prob([h, d, a])
        for i, (label, short, odds) in enumerate([
            (f"{home} Win (1)", "1", h), ("Draw (X)", "X", d), (f"{away} Win (2)", "2", a)
        ]):
            if odds >= 1.05:
                tier = "A" if probs[i] >= 70 else ("B+" if probs[i] >= 55 else ("B" if probs[i] >= 40 else "C"))
                plays.append({"market": "1X2", "pick": label, "pick_short": short, "odds": odds,
                    "implied": round(probs[i], 1), "tier": tier, "score": round(probs[i] * odds / 100, 2)})

    # BTTS
    gg_ng = markets.get("GG/NG", {})
    gg, ng = gg_ng.get("GG", 0), gg_ng.get("NG", 0)
    if gg and ng:
        probs = implied_prob([gg, ng])
        for idx, (label, short, odds) in enumerate([
            ("Both Teams Score (GG)", "GG", gg), ("No BTTS (NG)", "NG", ng)
        ]):
            if odds >= 1.05:
                tier = "A" if probs[idx] >= 70 else ("B+" if probs[idx] >= 55 else ("B" if probs[idx] >= 40 else "C"))
                plays.append({"market": "BTTS", "pick": label, "pick_short": short,
                    "odds": odds, "implied": round(probs[idx], 1), "tier": tier, "score": round(probs[idx] * odds / 100, 2)})

    # Over/Under
    for line in ["0.5", "1.5", "2.5", "3.5", "4.5"]:
        ou = markets.get(f"Over/Under(total={line})", {})
        over, under = ou.get("Over", 0), ou.get("Under", 0)
        if over and under:
            probs = implied_prob([over, under])
            for idx, (label, short, odds) in enumerate([
                (f"Over {line} Goals", f"O{line}", over), (f"Under {line} Goals", f"U{line}", under)
            ]):
                if odds >= 1.05:
                    tier = "A" if probs[idx] >= 80 else ("B+" if probs[idx] >= 65 else ("B" if probs[idx] >= 45 else "C"))
                    plays.append({"market": "Goals", "pick": label, "pick_short": short,
                        "odds": odds, "implied": round(probs[idx], 1), "tier": tier, "score": round(probs[idx] * odds / 100, 2)})

    # Handicap
    for hcp in ["0:1", "0:2", "0:3", "1:0", "2:0", "3:0"]:
        hcp_data = markets.get(f"Handicap {hcp}(hcp={hcp})", {})
        for outcome, odds_val in hcp_data.items():
            if odds_val and odds_val >= 1.10:
                prob = 100 / odds_val
                tier = "A" if prob >= 70 else ("B+" if prob >= 55 else "B")
                plays.append({"market": "Handicap", "pick": f"HCP {hcp} {outcome}",
                    "pick_short": f"H{hcp}{outcome}", "odds": odds_val, "implied": round(prob, 1),
                    "tier": tier, "score": round(prob * odds_val / 100, 2)})

    # Double Chance
    dc = markets.get("Double Chance", {})
    dc_labels = {"1X": f"{home} or Draw", "12": f"{home} or {away}", "X2": f"Draw or {away}"}
    for outcome, odds_val in dc.items():
        if odds_val and odds_val >= 1.05:
            prob = 100 / odds_val
            tier = "A" if prob >= 80 else ("B+" if prob >= 65 else "B")
            plays.append({"market": "Double Chance", "pick": dc_labels.get(outcome, outcome),
                "pick_short": outcome, "odds": odds_val, "implied": round(prob, 1), "tier": tier,
                "score": round(prob * odds_val / 100, 2)})

    # DNB
    dnb = markets.get("Draw No Bet", {})
    for outcome, odds_val in dnb.items():
        if odds_val and odds_val >= 1.10:
            prob = 100 / odds_val
            label = f"{home} DNB" if outcome == "1" else f"{away} DNB"
            tier = "A" if prob >= 70 else ("B+" if prob >= 55 else "B")
            plays.append({"market": "DNB", "pick": label, "pick_short": f"DNB{outcome}",
                "odds": odds_val, "implied": round(prob, 1), "tier": tier,
                "score": round(prob * odds_val / 100, 2)})

    plays.sort(key=lambda p: p["score"], reverse=True)
    return {"event_id": event.get("event_id", ""), "league": league, "home": home, "away": away,
            "start_time_ms": event.get("start_time_ms", 0), "markets": markets, "plays": plays}


def select_top_10(events):
    all_plays = []
    for ev in events:
        analysis = analyze_all_markets(ev)
        for play in analysis["plays"]:
            play["event_id"] = ev["event_id"]
            play["league"] = ev["league"]
            play["home"] = ev["home"]
            play["away"] = ev["away"]
            play["start_time_ms"] = ev["start_time_ms"]
            all_plays.append(play)
    if not all_plays:
        return []
    all_plays.sort(key=lambda p: p["score"], reverse=True)
    selected, match_count, market_count = [], {}, {}
    for play in all_plays:
        eid, mkt = play["event_id"], play["market"]
        if match_count.get(eid, 0) >= 2:
            continue
        if market_count.get(mkt, 0) >= 3:
            continue
        selected.append(play)
        match_count[eid] = match_count.get(eid, 0) + 1
        market_count[mkt] = market_count.get(mkt, 0) + 1
        if len(selected) >= 10:
            break
    return selected


def build_three_slips(top_10):
    if not top_10:
        return {"slip_a": [], "slip_b": [], "slip_c": [], "combined": {"a": 0, "b": 0, "c": 0}}
    used = set()
    slips = {"a": [], "b": [], "c": []}

    def fill(key, target_max, max_legs):
        for play in top_10:
            if len(slips[key]) >= max_legs:
                break
            if play["event_id"] in used:
                continue
            current = functools.reduce(lambda x, y: x * y, [p["odds"] for p in slips[key]], 1.0)
            if current * play["odds"] > target_max * 1.8:
                continue
            slips[key].append(play)
            used.add(play["event_id"])

    fill("a", 3.0, 2)
    fill("b", 7.0, 3)
    fill("c", 11.0, 5)

    combined = {}
    for key in ["a", "b", "c"]:
        if slips[key]:
            combined[key] = round(functools.reduce(lambda x, y: x * y, [p["odds"] for p in slips[key]], 1.0), 2)
        else:
            combined[key] = 0
    return {"slip_a": slips["a"], "slip_b": slips["b"], "slip_c": slips["c"], "combined": combined}


def generate_daily_picks(today_only=True):
    events = fetch_upcoming_events(page_size=100, today_only=today_only)
    if not events:
        return {"events": [], "top_10": [], "slips": {"slip_a": [], "slip_b": [], "slip_c": [], "combined": {}}}
    analyzed = [analyze_all_markets(ev) for ev in events]
    top_10 = select_top_10(events)
    slips = build_three_slips(top_10)
    return {"events": analyzed, "top_10": top_10, "slips": slips}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    result = generate_daily_picks()
    top = result["top_10"]
    for i, p in enumerate(top, 1):
        ts = "TBD"
        if p.get("start_time_ms"):
            try:
                ts = datetime.fromtimestamp(p["start_time_ms"] / 1000).strftime("%H:%M")
            except Exception:
                pass
        print(f"{i}. {p['home']} vs {p['away']} | {p['league']} | {ts}")
        print(f"   {p['market']}: {p['pick']} @ {p['odds']:.2f} | {p['implied']}% | Tier {p['tier']}")
    for key, label in [("slip_a", "SLIP A"), ("slip_b", "SLIP B"), ("slip_c", "SLIP C")]:
        slip = result["slips"][key]
        combined = result["slips"]["combined"][key[-1]]
        risk = "SAFE" if key == "slip_a" else "MODERATE" if key == "slip_b" else "HIGH"
        print(f"\n{label} ({combined:.1f}x) - {risk}:")
        for i, p in enumerate(slip, 1):
            print(f"  {i}. {p['home']} vs {p['away']} - {p['market']}: {p['pick']} @ {p['odds']:.2f} | Tier {p['tier']}")
