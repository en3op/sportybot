"""
Slip Matcher
============
Parses user-submitted bet slips (text) and cross-references
each match against the prediction pool.
"""

import logging
import re

logger = logging.getLogger(__name__)


TEAM_ALIASES = {
    "paris saint-germain": ["psg", "paris"],
    "atletico madrid": ["atletico", "at. madrid"],
    "bayern munich": ["bayern"],
    "manchester united": ["man united", "man utd"],
    "manchester city": ["man city"],
    "inter milan": ["inter"],
    "ac milan": ["milan"],
    "tottenham hotspur": ["tottenham", "spurs"],
    "wolverhampton wanderers": ["wolves"],
    "brighton & hove albion": ["brighton"],
    "west ham united": ["west ham"],
    "newcastle united": ["newcastle"],
    "real madrid": ["real"],
    "fc barcelona": ["barcelona"],
}

# Reverse lookup: alias -> canonical tokens
ALIAS_EXPANSIONS = {}
for canonical, aliases in TEAM_ALIASES.items():
    canon_tokens = canonical.lower().replace("-", " ").replace("'", "").split()
    for alias in aliases:
        ALIAS_EXPANSIONS[alias.lower()] = canon_tokens


def _normalize(name):
    return name.lower().replace("-", " ").replace("'", "").replace(".", "").replace("&", "").strip()


def _get_tokens(name):
    tokens = _normalize(name).split()

    # If name matches a canonical, add its aliases
    for canonical, aliases in TEAM_ALIASES.items():
        if _normalize(name) == canonical or _normalize(name).startswith(canonical):
            for a in aliases:
                tokens.extend(_normalize(a).split())

    # If name IS an alias, expand to canonical tokens
    name_lower = _normalize(name)
    if name_lower in ALIAS_EXPANSIONS:
        tokens.extend(ALIAS_EXPANSIONS[name_lower])

    return list(dict.fromkeys(tokens))


def parse_slip_text(text: str) -> list[dict]:
    """Parse raw text input into match objects.

    Supports formats like:
      - "PSG vs Toulouse"
      - "Paris Saint-Germain v Toulouse"
      - "PSG-Toulouse Over 2.5"
      - Multi-line with team names
    """
    matches = []
    lines = text.strip().split("\n")

    for line in lines:
        line = line.strip()
        if not line or len(line) < 5:
            continue

        # Try "Team A vs/v/- Team B" pattern
        vs_patterns = [
            r'(.+?)\s+(?:vs?\.?|[-])\s+(.+?)(?:\s+|$)',
            r'(.+?)\s+(?:v\s)(.+?)(?:\s+|$)',
        ]

        for pattern in vs_patterns:
            m = re.search(pattern, line, re.IGNORECASE)
            if m:
                home = m.group(1).strip()
                away = m.group(2).strip()

                # Clean up: remove bet info after team names
                for sep in ["over", "under", "1x2", "btts", "dnb", "handicap", "@", "odd"]:
                    away = re.split(rf'\s+{sep}', away, flags=re.IGNORECASE)[0].strip()

                if len(home) > 1 and len(away) > 1:
                    matches.append({
                        "home": home,
                        "away": away,
                        "raw_line": line,
                    })
                    break

    logger.info(f"Parsed {len(matches)} matches from slip text")
    return matches


def match_against_pool(parsed_matches: list[dict]) -> dict:
    """Match parsed slip matches against the prediction pool.

    Returns dict with:
      - matched: list of {match, predictions, pool_match}
      - unmatched: list of {match, reason}
    """
    from core.pool_manager import get_active_matches, get_predictions_for_match, get_research

    pool_matches = get_active_matches()

    matched = []
    unmatched = []

    for slip_match in parsed_matches:
        slip_home = slip_match["home"]
        slip_away = slip_match["away"]

        # Token matching against pool
        home_tokens = _get_tokens(slip_home)
        away_tokens = _get_tokens(slip_away)

        best_match = None
        best_score = 0

        for pool_m in pool_matches:
            pool_home = pool_m["home_team"]
            pool_away = pool_m["away_team"]

            # Check both directions (home vs home, away vs away)
            hm = _teams_match(slip_home, pool_home)
            am = _teams_match(slip_away, pool_away)

            if hm and am:
                score = _match_score(slip_home, pool_home) + _match_score(slip_away, pool_away)
                if score > best_score:
                    best_score = score
                    best_match = pool_m

            # Also check reverse (sometimes users list away team first)
            hm_rev = _teams_match(slip_home, pool_away)
            am_rev = _teams_match(slip_away, pool_home)
            if hm_rev and am_rev:
                score = _match_score(slip_home, pool_away) + _match_score(slip_away, pool_home)
                if score > best_score:
                    best_score = score
                    best_match = pool_m

        if best_match:
            preds = get_predictions_for_match(best_match["match_id"])
            research = get_research(best_match["match_id"])

            # Filter predictions to only high-quality ones
            good_preds = [p for p in preds if p["confidence"] >= 60]

            if good_preds:
                matched.append({
                    "slip_match": slip_match,
                    "pool_match": best_match,
                    "predictions": good_preds,
                    "research": dict(research) if research else None,
                })
            else:
                unmatched.append({
                    "slip_match": slip_match,
                    "reason": "No high-confidence predictions in pool",
                })
        else:
            unmatched.append({
                "slip_match": slip_match,
                "reason": "Match not found in prediction pool",
            })

    logger.info(f"Slip matching: {len(matched)} matched, {len(unmatched)} unmatched")
    return {"matched": matched, "unmatched": unmatched}


def _teams_match(name1: str, name2: str) -> bool:
    """Check if two team names refer to the same team."""
    n1 = _normalize(name1)
    n2 = _normalize(name2)

    if n1 == n2:
        return True

    # Check if one contains the other
    if n1 in n2 or n2 in n1:
        return True

    # Check token overlap
    t1 = _get_tokens(name1)
    t2 = _get_tokens(name2)

    # At least one significant token from each must match
    significant1 = [t for t in t1 if len(t) > 2]
    significant2 = [t for t in t2 if len(t) > 2]

    if significant1 and significant2:
        overlap = set(significant1) & set(significant2)
        if overlap:
            return True

    return False


def _match_score(name1: str, name2: str) -> int:
    """Score how well two names match (higher = better)."""
    n1 = _normalize(name1)
    n2 = _normalize(name2)

    if n1 == n2:
        return 10

    t1 = set(_get_tokens(name1))
    t2 = set(_get_tokens(name2))
    overlap = t1 & t2

    return len(overlap) * 3
