"""
Elite Football Betting Analysis Engine
=======================================
Rigorous, data-driven match analysis with edge scoring.
Only outputs picks with demonstrable statistical edge (score 7+).

Scoring weights:
  Data Reliability:     30%
  Predictability:       30%
  Strength Mismatch:    25%
  Goal Trend Clarity:   15%
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ──────────────────────────────────────────────
# DATA STRUCTURES
# ──────────────────────────────────────────────

class EdgeTier(Enum):
    PRIME = "PRIME PICKS (8-10)"
    VALUE = "VALUE PICKS (7-7.9)"
    SPECULATIVE = "SPECULATIVE ANGLES (7+)"
    DISCARD = "BELOW THRESHOLD"


@dataclass
class TeamMetrics:
    """Parsed metrics for one team from API-Football data."""
    name: str
    form: str                    # e.g., "WWDLW"
    ppg: float                   # Points per game (last 5)
    goals_scored_avg: float      # Avg goals scored per game
    goals_conceded_avg: float    # Avg goals conceded per game
    league_position: int = 0
    goal_difference: int = 0
    home_wins: int = 0
    home_draws: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_draws: int = 0
    away_losses: int = 0
    streak_type: str = ""        # "W", "D", or "L"
    streak_length: int = 0


@dataclass
class MatchEdge:
    """Complete analysis result for a single fixture."""
    home: str
    away: str
    competition: str
    match_time: str
    edge_score: float            # 1-10
    edge_tier: EdgeTier
    confidence: str              # High / Medium / Low

    best_bet: str
    best_bet_reasoning: str
    secondary_bet: str           # e.g., goals market
    secondary_reasoning: str
    odds_range: str

    # Sub-scores
    data_reliability: float
    predictability: float
    strength_mismatch: float
    goal_trend_clarity: float

    # Detail flags
    risk_flags: list[str] = field(default_factory=list)
    home_metrics: TeamMetrics | None = None
    away_metrics: TeamMetrics | None = None


# ──────────────────────────────────────────────
# METRIC EXTRACTION
# ──────────────────────────────────────────────

def extract_team_metrics(
    fixtures: list[dict],
    team_id: int,
    team_name: str,
    stats: dict | None,
    league_position: int = 0,
    goal_difference: int = 0,
) -> TeamMetrics:
    """Extract all metrics from raw API-Football data.

    Args:
        fixtures: Last 5 fixtures from API-Football (newest first).
        team_id: The team's API-Football ID.
        team_name: Team display name.
        stats: Team statistics from API-Football (may be None).
        league_position: Current league table position.
        goal_difference: Season goal difference.
    """
    # Parse form from fixtures
    form_chars = []
    goals_scored = []
    goals_conceded = []
    results = []  # "W", "D", "L" per match

    for fx in reversed(fixtures):  # Chronological order
        home = fx["teams"]["home"]
        away = fx["teams"]["away"]
        hg = fx["goals"]["home"]
        ag = fx["goals"]["away"]

        if hg is None or ag is None:
            continue

        if home["id"] == team_id:
            goals_scored.append(hg)
            goals_conceded.append(ag)
            if hg > ag:
                results.append("W")
            elif hg == ag:
                results.append("D")
            else:
                results.append("L")
        else:
            goals_scored.append(ag)
            goals_conceded.append(hg)
            if ag > hg:
                results.append("W")
            elif ag == hg:
                results.append("D")
            else:
                results.append("L")

    form = "".join(results)

    # PPG
    points = sum(3 if r == "W" else 1 if r == "D" else 0 for r in results)
    ppg = points / len(results) if results else 0.0

    # Goal averages
    avg_scored = sum(goals_scored) / len(goals_scored) if goals_scored else 0.0
    avg_conceded = sum(goals_conceded) / len(goals_conceded) if goals_conceded else 0.0

    # Streak detection
    streak_type = ""
    streak_length = 0
    if results:
        current = results[-1]
        count = 0
        for r in reversed(results):
            if r == current:
                count += 1
            else:
                break
        if count >= 3:
            streak_type = current
            streak_length = count

    # Home/away splits from stats
    hw, hd, hl, aw, ad, al = 0, 0, 0, 0, 0, 0
    if stats:
        try:
            fixtures_stats = stats.get("fixtures", {})
            played = fixtures_stats.get("played", {})
            wins = fixtures_stats.get("wins", {})
            draws = fixtures_stats.get("draws", {})
            losses = fixtures_stats.get("loses", {})
            hw = wins.get("home", 0) or 0
            hd = draws.get("home", 0) or 0
            hl = losses.get("home", 0) or 0
            aw = wins.get("away", 0) or 0
            ad = draws.get("away", 0) or 0
            al = losses.get("away", 0) or 0
        except (AttributeError, TypeError):
            pass

    # Override goals from stats if available (season averages are more reliable)
    if stats:
        try:
            goals = stats.get("goals", {})
            for_avg = goals.get("for", {}).get("average", {})
            against_avg = goals.get("against", {}).get("average", {})
            total_for = for_avg.get("total")
            total_against = against_avg.get("total")
            if total_for:
                avg_scored = float(total_for)
            if total_against:
                avg_conceded = float(total_against)
        except (AttributeError, TypeError, ValueError):
            pass

    return TeamMetrics(
        name=team_name,
        form=form,
        ppg=round(ppg, 2),
        goals_scored_avg=round(avg_scored, 2),
        goals_conceded_avg=round(avg_conceded, 2),
        league_position=league_position,
        goal_difference=goal_difference,
        home_wins=hw,
        home_draws=hd,
        home_losses=hl,
        away_wins=aw,
        away_draws=ad,
        away_losses=al,
        streak_type=streak_type,
        streak_length=streak_length,
    )


# ──────────────────────────────────────────────
# EDGE SCORING COMPONENTS
# ──────────────────────────────────────────────

def _score_data_reliability(home: TeamMetrics, away: TeamMetrics) -> float:
    """Score 0-10 based on data quality and completeness.

    Factors:
      - Form string length (5 matches = best)
      - Stats availability
      - League position data
    """
    score = 5.0  # Base

    # Form completeness
    form_len = min(len(home.form), len(away.form))
    if form_len >= 5:
        score += 2.0
    elif form_len >= 4:
        score += 1.5
    elif form_len >= 3:
        score += 1.0

    # Goals data available
    if home.goals_scored_avg > 0 and away.goals_scored_avg > 0:
        score += 1.5

    # League position data
    if home.league_position > 0 and away.league_position > 0:
        score += 1.0

    # Home/away splits
    total_matches = (home.home_wins + home.home_draws + home.home_losses +
                     away.away_wins + away.away_draws + away.away_losses)
    if total_matches >= 10:
        score += 0.5

    return min(score, 10.0)


def _score_predictability(home: TeamMetrics, away: TeamMetrics) -> float:
    """Score 0-10 based on how clear the statistical edge is.

    Factors:
      - PPG gap between teams
      - Consistency of form
      - Clear favorite identifiable
    """
    score = 3.0

    # PPG gap
    ppg_gap = abs(home.ppg - away.ppg)
    if ppg_gap >= 1.5:
        score += 3.5
    elif ppg_gap >= 1.0:
        score += 2.5
    elif ppg_gap >= 0.5:
        score += 1.5
    else:
        score += 0.5

    # Streak clarity (3+ game streak = strong signal)
    if home.streak_length >= 3 or away.streak_length >= 3:
        score += 1.5
    if home.streak_length >= 4 or away.streak_length >= 4:
        score += 0.5

    # Form consistency (low variance in results)
    def _form_consistency(form: str) -> float:
        if len(form) < 3:
            return 0
        w = form.count("W")
        l = form.count("L")
        # All same = very consistent
        if w == len(form) or l == len(form):
            return 2.0
        if w >= len(form) - 1 or l >= len(form) - 1:
            return 1.5
        return 0.5

    score += max(_form_consistency(home.form), _form_consistency(away.form))

    return min(score, 10.0)


def _score_strength_mismatch(home: TeamMetrics, away: TeamMetrics) -> float:
    """Score 0-10 based on objective gap in team quality.

    Factors:
      - League position gap
      - Goal difference gap
      - Home/away record disparity
    """
    score = 3.0

    # League position gap
    if home.league_position > 0 and away.league_position > 0:
        pos_gap = abs(home.league_position - away.league_position)
        if pos_gap >= 10:
            score += 3.0
        elif pos_gap >= 6:
            score += 2.0
        elif pos_gap >= 3:
            score += 1.0

    # Goal difference gap
    if home.goal_difference != 0 or away.goal_difference != 0:
        gd_gap = abs(home.goal_difference - away.goal_difference)
        if gd_gap >= 20:
            score += 2.0
        elif gd_gap >= 10:
            score += 1.5
        elif gd_gap >= 5:
            score += 1.0

    # Home advantage factor
    home_total = home.home_wins + home.home_draws + home.home_losses
    away_total = away.away_wins + away.away_draws + away.away_losses
    if home_total > 0 and away_total > 0:
        home_win_rate = home.home_wins / home_total
        away_win_rate = away.away_wins / away_total
        if home_win_rate > 0.6 and away_win_rate < 0.3:
            score += 2.0
        elif home_win_rate > 0.5 and away_win_rate < 0.4:
            score += 1.0

    return min(score, 10.0)


def _score_goal_trend(home: TeamMetrics, away: TeamMetrics) -> float:
    """Score 0-10 based on clarity of over/under goal patterns.

    Factors:
      - Combined goals per game
      - Defensive weakness
      - Offensive strength
    """
    score = 3.0

    combined_avg = home.goals_scored_avg + away.goals_scored_avg
    combined_conceded = home.goals_conceded_avg + away.goals_conceded_avg

    # High-scoring pattern
    if combined_avg >= 3.5:
        score += 3.0
    elif combined_avg >= 2.5:
        score += 2.0
    elif combined_avg >= 2.0:
        score += 1.0

    # Defensive weakness (high conceded)
    if combined_conceded >= 3.0:
        score += 2.0
    elif combined_conceded >= 2.0:
        score += 1.0

    # One-sided offensive/defensive imbalance
    if home.goals_scored_avg > 2.0 and away.goals_conceded_avg > 1.5:
        score += 1.5
    if away.goals_scored_avg > 2.0 and home.goals_conceded_avg > 1.5:
        score += 1.5

    return min(score, 10.0)


# ──────────────────────────────────────────────
# RISK AUDIT
# ──────────────────────────────────────────────

def _audit_risks(home: TeamMetrics, away: TeamMetrics) -> list[str]:
    """Flag red flags that reduce edge reliability."""
    flags = []

    # High draw frequency
    home_total = home.home_wins + home.home_draws + home.home_losses
    away_total = away.away_wins + away.away_draws + away.away_losses
    if home_total > 0:
        home_draw_rate = home.home_draws / home_total
        if home_draw_rate > 0.4:
            flags.append(f"High home draw rate ({home.home_draws}/{home_total})")
    if away_total > 0:
        away_draw_rate = away.away_draws / away_total
        if away_draw_rate > 0.4:
            flags.append(f"High away draw rate ({away.away_draws}/{away_total})")

    # Erratic form (mix of W/D/L without pattern)
    if len(home.form) >= 4:
        if "W" in home.form and "L" in home.form and "D" in home.form:
            if home.form.count("W") <= 2 and home.form.count("L") <= 2:
                flags.append(f"{home.name} has erratic form: {home.form}")
    if len(away.form) >= 4:
        if "W" in away.form and "L" in away.form and "D" in away.form:
            if away.form.count("W") <= 2 and away.form.count("L") <= 2:
                flags.append(f"{away.name} has erratic form: {away.form}")

    # Losing streak
    if home.streak_type == "L" and home.streak_length >= 3:
        flags.append(f"{home.name} on {home.streak_length}-game losing streak")
    if away.streak_type == "L" and away.streak_length >= 3:
        flags.append(f"{away.name} on {away.streak_length}-game losing streak")

    # Very low-scoring (boring match likely)
    combined = home.goals_scored_avg + away.goals_scored_avg
    if combined < 1.5:
        flags.append(f"Very low-scoring teams (combined avg: {combined:.1f})")

    # Evenly matched (no clear edge)
    ppg_gap = abs(home.ppg - away.ppg)
    if ppg_gap < 0.3 and abs(home.league_position - away.league_position) <= 2:
        flags.append("Teams are evenly matched - unpredictable outcome")

    return flags


# ──────────────────────────────────────────────
# BET GENERATION
# ──────────────────────────────────────────────

def _determine_best_bet(home: TeamMetrics, away: TeamMetrics) -> tuple[str, str]:
    """Determine the best 1X2 bet and reasoning."""
    h_ppg = home.ppg
    a_ppg = away.ppg

    # Home advantage factor (~0.3 PPG boost at home)
    h_adj = h_ppg + 0.3
    a_adj = a_ppg  # Away teams don't get bonus

    gap = h_adj - a_adj

    if gap >= 1.5:
        return (
            f"{home.name} Win (1)",
            f"{home.name} PPG ({home.ppg}) dominates {away.name} ({away.ppg}). "
            f"Home advantage widens the gap. "
            f"Home: {home.home_wins}W {home.home_draws}D {home.home_losses}L at home."
        )
    elif gap <= -1.5:
        return (
            f"{away.name} Win (2)",
            f"{away.name} PPG ({away.ppg}) clearly beats {home.name} ({home.ppg}). "
            f"Away: {away.away_wins}W {away.away_draws}D {away.away_losses}L away."
        )
    elif gap >= 0.5:
        return (
            f"{home.name} or Draw (1X)",
            f"Slight home edge (adj PPG: {h_adj:.1f} vs {a_adj:.1f}). "
            f"Double chance covers the draw risk."
        )
    elif gap <= -0.5:
        return (
            f"{away.name} or Draw (X2)",
            f"Slight away edge (adj PPG: {a_adj:.1f} vs {h_adj:.1f}). "
            f"Double chance covers the draw risk."
        )
    else:
        # Dead even — recommend Double Chance
        if home.home_wins > away.away_wins:
            return (
                f"{home.name} or Draw (1X)",
                f"Evenly matched but home record ({home.home_wins}W) gives slight edge."
            )
        else:
            return (
                f"Double Chance (1X or X2)",
                f"Dead even matchup. No clear winner — play it safe."
            )


def _determine_goals_bet(home: TeamMetrics, away: TeamMetrics) -> tuple[str, str]:
    """Determine the best goals market bet and reasoning."""
    combined_avg = home.goals_scored_avg + away.goals_scored_avg
    combined_conceded = home.goals_conceded_avg + away.goals_conceded_avg

    # Over 2.5 probability estimate
    # Based on combined average: 2.5+ goals = likely Over 2.5
    over25_est = min(max((combined_avg - 1.5) / 2.0, 0), 1) * 100

    if combined_avg >= 3.5:
        return (
            "Over 2.5 Goals",
            f"Combined avg {combined_avg:.1f} goals/game. "
            f"{home.name} scores {home.goals_scored_avg}, {away.name} concedes {away.goals_conceded_avg}. "
            f"Estimated Over 2.5 probability: ~{over25_est:.0f}%."
        )
    elif combined_avg >= 2.8:
        return (
            "Over 2.5 Goals",
            f"Combined avg {combined_avg:.1f} goals/game. "
            f"Both teams contribute to scoring. "
            f"Estimated Over 2.5 probability: ~{over25_est:.0f}%."
        )
    elif combined_avg >= 2.2:
        return (
            "Over 1.5 Goals",
            f"Combined avg {combined_avg:.1f} goals/game. "
            f"Over 1.5 is the safer play here."
        )
    else:
        return (
            "Under 2.5 Goals",
            f"Low-scoring sides (combined avg {combined_avg:.1f}). "
            f"Both teams are defensively solid."
        )


def _estimate_odds_range(
    home: TeamMetrics, away: TeamMetrics, best_bet: str
) -> str:
    """Estimate the likely odds range based on team strength."""
    h_ppg = home.ppg
    a_ppg = away.ppg
    gap = abs(h_ppg - a_ppg)

    if "Win" in best_bet and "or" not in best_bet:
        if gap >= 1.5:
            return "1.40-1.70"
        elif gap >= 1.0:
            return "1.70-2.10"
        else:
            return "2.10-2.60"
    elif "or Draw" in best_bet or "1X" in best_bet or "X2" in best_bet:
        if gap >= 1.0:
            return "1.20-1.45"
        else:
            return "1.35-1.65"
    elif "Over 2.5" in best_bet:
        return "1.65-1.95"
    elif "Over 1.5" in best_bet:
        return "1.25-1.45"
    elif "Under 2.5" in best_bet:
        return "1.60-1.90"
    return "1.70-2.00"


# ──────────────────────────────────────────────
# MASTER ANALYZER
# ──────────────────────────────────────────────

def analyze_match_edge(
    home_metrics: TeamMetrics,
    away_metrics: TeamMetrics,
    competition: str,
    match_time: str,
) -> MatchEdge | None:
    """Run the full edge analysis on a fixture.

    Returns MatchEdge if score >= 7, else None.
    """
    # Sub-scores
    dr = _score_data_reliability(home_metrics, away_metrics)
    pr = _score_predictability(home_metrics, away_metrics)
    sm = _score_strength_mismatch(home_metrics, away_metrics)
    gt = _score_goal_trend(home_metrics, away_metrics)

    # Weighted edge score
    edge = (dr * 0.30) + (pr * 0.30) + (sm * 0.25) + (gt * 0.15)
    edge = round(edge, 1)

    # Risk audit
    risks = _audit_risks(home_metrics, away_metrics)

    # Deduct for risk flags
    if len(risks) >= 3:
        edge -= 1.0
    elif len(risks) >= 2:
        edge -= 0.5

    edge = max(edge, 1.0)
    edge = min(edge, 10.0)

    # Filter: discard below 7
    if edge < 7.0:
        return None

    # Tier classification
    if edge >= 8.0:
        tier = EdgeTier.PRIME
    elif edge >= 7.0:
        tier = EdgeTier.VALUE
    else:
        return None

    # Confidence
    if edge >= 8.5:
        confidence = "High"
    elif edge >= 7.5:
        confidence = "Medium"
    else:
        confidence = "Low"

    # Bets
    best_bet, best_reasoning = _determine_best_bet(home_metrics, away_metrics)
    goals_bet, goals_reasoning = _determine_goals_bet(home_metrics, away_metrics)
    odds_range = _estimate_odds_range(home_metrics, away_metrics, best_bet)

    return MatchEdge(
        home=home_metrics.name,
        away=away_metrics.name,
        competition=competition,
        match_time=match_time,
        edge_score=edge,
        edge_tier=tier,
        confidence=confidence,
        best_bet=best_bet,
        best_bet_reasoning=best_reasoning,
        secondary_bet=goals_bet,
        secondary_reasoning=goals_reasoning,
        odds_range=odds_range,
        data_reliability=round(dr, 1),
        predictability=round(pr, 1),
        strength_mismatch=round(sm, 1),
        goal_trend_clarity=round(gt, 1),
        risk_flags=risks,
        home_metrics=home_metrics,
        away_metrics=away_metrics,
    )


# ──────────────────────────────────────────────
# TELEGRAM MESSAGE FORMATTER
# ──────────────────────────────────────────────

def format_edge_message(edges: list[MatchEdge]) -> list[str]:
    """Format edges into Telegram-ready message chunks.

    Returns a list of messages (split by tier).
    """
    if not edges:
        return ["No qualifying picks found today. Edge score < 7 for all matches."]

    # Sort by edge score descending
    edges.sort(key=lambda e: e.edge_score, reverse=True)

    prime = [e for e in edges if e.edge_tier == EdgeTier.PRIME]
    value = [e for e in edges if e.edge_tier == EdgeTier.VALUE]

    messages = []

    # Header
    header = (
        "VIP ANALYSIS\n"
        "=" * 28 + "\n"
        f"Date: {edges[0].match_time[:10] if edges[0].match_time else 'Today'}\n"
        f"Matches analyzed: {len(edges)} qualifying edges found\n"
    )
    messages.append(header)

    # Prime picks
    if prime:
        msg = "\n" + "-" * 28 + "\n"
        msg += "PRIME PICKS (Edge 8-10)\n"
        msg += "-" * 28 + "\n\n"
        for e in prime:
            msg += _format_single_edge(e)
        messages.append(msg)

    # Value picks
    if value:
        msg = "\n" + "-" * 28 + "\n"
        msg += "VALUE PICKS (Edge 7-7.9)\n"
        msg += "-" * 28 + "\n\n"
        for e in value:
            msg += _format_single_edge(e)
        messages.append(msg)

    # Footer
    footer = (
        "-" * 28 + "\n"
        "Edge Score = Data Reliability (30%) + Predictability (30%) "
        "+ Strength Mismatch (25%) + Goal Trend (15%)\n"
        "\nOnly picks with edge >= 7 are shown.\n"
        "Track results over 100+ bets to validate edge.\n"
    )
    messages.append(footer)

    return messages


def _format_single_edge(e: MatchEdge) -> str:
    """Format one match edge into readable text."""
    lines = []
    lines.append(f"Match: {e.home} vs {e.away}")
    lines.append(f"Competition: {e.competition}")
    lines.append(f"Edge: {e.edge_score}/10 | Confidence: {e.confidence}")
    lines.append("")

    # Form context
    hm = e.home_metrics
    am = e.away_metrics
    if hm and am:
        lines.append(f"  {hm.name}: Form {hm.form} | PPG {hm.ppg} | "
                     f"GF {hm.goals_scored_avg} GA {hm.goals_conceded_avg}")
        if hm.streak_length >= 3:
            streak_label = {"W": "WINNING", "L": "LOSING", "D": "DRAW"}.get(hm.streak_type, "")
            lines.append(f"  !! {streak_label} STREAK: {hm.streak_length} games")
        lines.append(f"  {am.name}: Form {am.form} | PPG {am.ppg} | "
                     f"GF {am.goals_scored_avg} GA {am.goals_conceded_avg}")
        if am.streak_length >= 3:
            streak_label = {"W": "WINNING", "L": "LOSING", "D": "DRAW"}.get(am.streak_type, "")
            lines.append(f"  !! {streak_label} STREAK: {am.streak_length} games")
    lines.append("")

    # Best bet
    lines.append(f"Best Bet: {e.best_bet}")
    lines.append(f"Odds Range: {e.odds_range}")
    lines.append(f"  {e.best_bet_reasoning}")
    lines.append("")

    # Secondary bet
    lines.append(f"Secondary: {e.secondary_bet}")
    lines.append(f"  {e.secondary_reasoning}")
    lines.append("")

    # Sub-scores
    lines.append(f"  Data: {e.data_reliability}/10 | "
                 f"Predict: {e.predictability}/10 | "
                 f"Mismatch: {e.strength_mismatch}/10 | "
                 f"Goals: {e.goal_trend_clarity}/10")

    # Risk flags
    if e.risk_flags:
        lines.append(f"  Flags: {'; '.join(e.risk_flags)}")

    lines.append("")
    lines.append("- - - - - - - - - - - -")
    lines.append("")

    return "\n".join(lines)
