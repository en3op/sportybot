"""
Slip Parser — Accepts raw input from Telegram and normalizes into structured picks.
Supports text, forwarded messages, and basic pattern matching.
"""

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Pick:
    """A single betting pick extracted from user input."""
    match_name: str
    bet_type: str
    odds: float
    raw_line: str = ""
    league: str = ""
    position: int = 0  # position in the original slip


# SportyBet UI noise — these are never real picks
SKIP_PATTERNS = [
    # Bet button labels: "@) Home", "@) Draw", "@) Away"
    r"^@?\)?\s*(home|draw|away)\s*$",
    # Promotional labels
    r"max\s*bonus",
    r"welcome\s*bonus",
    r"boost\s*odds",
    r"odds\s*boost",
    # Betslip metadata
    r"total\s*odds",
    r"potential\s*win",
    r"possible\s*win",
    r"stake\s*:?\s*$",
    r"payout\s*:?\s*$",
    r"returns?\s*:?\s*$",
    r"bet\s*slip",
    # Standalone bet type labels (not attached to a match)
    r"^(1x2|over|under|btts|gg|ng|double\s*chance|dnb)\s*$",
    # SportyBet navigation labels
    r"^(popular|today|live|upcoming|football|soccer)\s*$",
    # Time-only lines like "12:00" or "HT"
    r"^\d{1,2}:\d{2}$",
    r"^(ht|ft|live|upcoming)$",
]

_SKIP_RE = re.compile("|".join(SKIP_PATTERNS), re.IGNORECASE)


def parse_slip(raw_input: str) -> list[Pick]:
    """
    Parse raw text input into a list of structured Pick objects.

    Handles formats like:
    - "Man City vs Arsenal - 1 @ 1.45"
    - "Barcelona vs Real Madrid, Over 2.5, 1.85"
    - "PSG win @ 1.30"
    - "Liverpool vs Chelsea BTTS Yes 1.70"
    - "Match: Bayern vs Dortmund | Pick: 1 | Odds: 1.50"

    Returns empty list if input is unparseable.
    """
    if not raw_input or not raw_input.strip():
        return []

    lines = _normalize_input(raw_input)
    picks = []

    for i, line in enumerate(lines):
        pick = _parse_line(line, i + 1)
        if pick:
            picks.append(pick)

    return picks


def extract_match_names(raw_input: str) -> list[tuple[str, str]]:
    """Extract team name pairs from raw input for API matching.

    Returns list of (team1, team2) tuples found in the input.
    Only returns matches that have both team names with a vs/v separator.
    """
    if not raw_input or not raw_input.strip():
        return []

    lines = _normalize_input(raw_input)
    matches = []
    seen = set()

    # Pattern: "Team A vs Team B"
    vs_pattern = re.compile(
        r"([A-Za-z][A-Za-z\s\.]{1,30}?)\s+(?:vs?\.?|[-])\s+([A-Za-z][A-Za-z\s\.]{1,30}?)\s*$",
        re.IGNORECASE,
    )

    for line in lines:
        m = vs_pattern.search(line)
        if m:
            t1 = m.group(1).strip().rstrip(".")
            t2 = m.group(2).strip().rstrip(".")
            key = f"{t1.lower()}|{t2.lower()}"
            if key not in seen and len(t1) >= 2 and len(t2) >= 2:
                matches.append((t1, t2))
                seen.add(key)

    return matches


def _normalize_input(raw: str) -> list[str]:
    """Split input into individual pick lines, stripping noise."""
    # Replace common separators with newlines
    text = raw.replace("\\n", "\n")
    text = re.sub(r"(\d+)\.\s", r"\n\1. ", text)  # "1. Pick 2. Pick" -> split
    text = re.sub(r"[-–—]{3,}", "\n", text)  # separator lines
    text = re.sub(r"[=]{3,}", "\n", text)  # separator lines

    lines = []
    for line in text.split("\n"):
        line = line.strip()
        # Skip empty lines
        if not line:
            continue
        # Skip comments
        if line.startswith("#") or line.startswith("//"):
            continue
        # Skip known SportyBet UI noise
        if _SKIP_RE.search(line):
            continue
        # Skip slip header/footer labels
        if re.match(r"^(slip|bet|ticket|accumulator|acca)\b", line, re.IGNORECASE):
            continue
        if re.match(r"^(total|combined|payout|stake|returns?)\b", line, re.IGNORECASE):
            continue
        # Skip lines that are just numbers or just odds
        if re.match(r"^[\d.,]+$", line):
            continue
        # Skip very short lines that are likely UI fragments
        if len(line) < 4:
            continue
        lines.append(line)

    return lines


def _parse_line(line: str, position: int) -> Optional[Pick]:
    """Parse a single line into a Pick object."""
    # Remove leading numbering like "1. " or "- "
    cleaned = re.sub(r"^[\d]+[.)]\s*", "", line)
    cleaned = re.sub(r"^[-*•]\s*", "", cleaned)
    cleaned = cleaned.strip()

    if not cleaned:
        return None

    # Try multiple parsing strategies in order of specificity
    pick = (
        _parse_structured(cleaned, position)
        or _parse_match_bet_odds(cleaned, position)
        or _parse_team_bet_odds(cleaned, position)
        or _parse_loose(cleaned, position)
    )

    return pick


def _parse_structured(line: str, position: int) -> Optional[Pick]:
    """
    Parse structured format: "Match: X vs Y | Pick: Z | Odds: N.NN"
    """
    match_name = None
    bet_type = None
    odds = None

    # Extract match
    match_m = re.search(r"(?:match|game|fixture)\s*[:=]\s*(.+?)(?:\||$)", line, re.IGNORECASE)
    if match_m:
        match_name = match_m.group(1).strip()
        vs_m = re.search(r"(.+?)\s+(?:vs?\.?|[-@])\s+(.+)", match_name, re.IGNORECASE)
        if vs_m:
            match_name = f"{vs_m.group(1).strip()} vs {vs_m.group(2).strip()}"

    # Extract pick/bet
    pick_m = re.search(r"(?:pick|bet|selection)\s*[:=]\s*(.+?)(?:\||$)", line, re.IGNORECASE)
    if pick_m:
        bet_type = pick_m.group(1).strip()

    # Extract odds
    odds_m = re.search(r"(?:odds|price|@)\s*[:=]?\s*(\d+\.?\d*)", line, re.IGNORECASE)
    if odds_m:
        odds = float(odds_m.group(1))

    if bet_type and odds:
        return Pick(
            match_name=match_name or "Unknown Match",
            bet_type=bet_type,
            odds=odds,
            raw_line=line,
            position=position,
        )

    return None


def _parse_match_bet_odds(line: str, position: int) -> Optional[Pick]:
    """
    Parse "Team A vs Team B - BetType @ Odds" or "Team A vs Team B, BetType, Odds"
    """
    # Pattern: "Team vs Team separator BetType separator Odds"
    patterns = [
        r"(.+?)\s+(?:vs?\.?|[-@])\s+(.+?)\s*[-–—|,]\s*(.+?)\s*[@:]\s*(\d+\.?\d*)",
        r"(.+?)\s+(?:vs?\.?|[-@])\s+(.+?)\s*[-–—|,]\s*(.+?)\s+(\d+\.?\d*)",
        r"(.+?)\s+(?:vs?\.?|[-@])\s+(.+?)\s+(.+?)\s+@?\s*(\d+\.?\d*)",
    ]

    for pattern in patterns:
        m = re.search(pattern, line, re.IGNORECASE)
        if m:
            team1 = m.group(1).strip()
            team2 = m.group(2).strip()
            bet_type = m.group(3).strip()
            odds = float(m.group(4))

            if 1.0 <= odds <= 100.0:
                return Pick(
                    match_name=f"{team1} vs {team2}",
                    bet_type=bet_type,
                    odds=odds,
                    raw_line=line,
                    position=position,
                )

    return None


def _parse_team_bet_odds(line: str, position: int) -> Optional[Pick]:
    """
    Parse "TeamName win @ Odds" or "TeamName BetType Odds"
    """
    m = re.search(r"^([A-Za-z\s.]+?)\s+(win|draw|1|2|x|dnb|btts|over|under)\s*@?\s*(\d+\.?\d*)",
                  line, re.IGNORECASE)
    if m:
        team = m.group(1).strip()
        bet = m.group(2).strip()
        odds = float(m.group(3))

        if 1.0 <= odds <= 100.0:
            return Pick(
                match_name=f"{team} match",
                bet_type=f"{team} {bet}" if bet in ("win", "draw") else bet,
                odds=odds,
                raw_line=line,
                position=position,
            )

    return None


def _parse_loose(line: str, position: int) -> Optional[Pick]:
    """
    Last resort: find any odds value and treat everything else as match+bet.
    Much stricter than before — requires a vs/v separator or at least 8 chars of context.
    """
    # Find the last number that looks like odds (1.01 to 99.99)
    odds_matches = list(re.finditer(r"\b(\d{1,2}\.\d{1,2})\b", line))

    for m in reversed(odds_matches):
        odds = float(m.group(1))
        if 1.01 <= odds <= 99.99:
            # Everything before the odds is match + bet
            before = line[:m.start()].strip()
            after = line[m.end():].strip()

            # Clean up separators
            before = re.sub(r"[@:#]\s*$", "", before).strip()
            before = re.sub(r"^\d+[.)]\s*", "", before).strip()

            # Reject if too short — likely a UI fragment
            if len(before) < 6:
                continue

            # Reject if it matches known noise patterns
            if _SKIP_RE.search(before):
                continue

            # Require a vs/v separator OR at least 2 meaningful words
            has_vs = bool(re.search(r'\bvs?\.?\b', before, re.IGNORECASE))
            word_count = len(before.split())
            if not has_vs and word_count < 3:
                continue

            return Pick(
                match_name=before,
                bet_type=after if after else "unknown",
                odds=odds,
                raw_line=line,
                position=position,
            )

    return None


def validate_picks(picks: list[Pick]) -> tuple[bool, str]:
    """
    Validate parsed picks. Returns (is_valid, error_message).
    """
    if not picks:
        return False, "No picks found. Paste your slip as text."

    if len(picks) < 2:
        return False, "Need at least 2 picks to analyze."

    if len(picks) > 15:
        return False, "Too many picks (max 15). Split into smaller slips."

    for p in picks:
        if p.odds < 1.01:
            return False, f"Invalid odds ({p.odds}) for {p.match_name}."
        if p.odds > 100.0:
            return False, f"Suspicious odds ({p.odds}) for {p.match_name}."

    return True, ""
