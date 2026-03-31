"""
VIP Slip Engine
===============
Generates intelligent VIP slips with AI-powered analysis.
Provides shuffle functionality for admin to customize picks.
"""

import logging
import random
import json
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

NVIDIA_API_KEY = "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"
NVIDIA_MODEL = "z-ai/glm5"


def get_nvidia_client():
    """Get NVIDIA NIM API client."""
    try:
        from openai import OpenAI
        return OpenAI(
            base_url="https://integrate.api.nvidia.com/v1",
            api_key=NVIDIA_API_KEY,
            timeout=60.0,
            max_retries=2
        )
    except Exception as e:
        logger.warning(f"Could not initialize NVIDIA client: {e}")
        return None


def call_ai(prompt: str, max_tokens: int = 1500) -> Optional[str]:
    """Call NVIDIA AI with a prompt."""
    client = get_nvidia_client()
    if not client:
        return None
    try:
        response = client.chat.completions.create(
            model=NVIDIA_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
            temperature=0.7,
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error(f"AI call failed: {e}")
        return None


def generate_vip_slips(matches: list[dict], use_ai: bool = True) -> dict:
    """
    Generate 3 VIP slips from today's approved predictions.
    
    Args:
        matches: List of match dicts with predictions
        use_ai: Whether to use AI for intelligent selection
    
    Returns:
        dict with slip_a, slip_b, slip_c and metadata
    """
    all_picks = []
    for match in matches:
        match_date = match.get("match_date", "")
        for pred in match.get("predictions", []):
            all_picks.append({
                "match_id": match.get("match_id"),
                "home": match.get("home_team"),
                "away": match.get("away_team"),
                "league": match.get("league", ""),
                "time": match_date[11:16] if len(match_date) > 11 else "TBD",
                "date": match_date[:10] if len(match_date) >= 10 else "",
                "market": pred.get("market"),
                "pick": pred.get("pick"),
                "odds": pred.get("odds", 1.85),
                "confidence": pred.get("confidence", 75),
                "tier": pred.get("risk_tier", "B"),
                "reasoning": pred.get("reasoning", ""),
            })
    
    if not all_picks:
        return _empty_slips()
    
    if use_ai:
        return _generate_ai_slips(all_picks)
    else:
        return _generate_rule_based_slips(all_picks)


def _generate_ai_slips(picks: list[dict]) -> dict:
    """Use AI to intelligently select picks for each slip tier using APEX framework."""
    
    picks_summary = "\n".join([
        f"#{i+1}. {p['home']} vs {p['away']} | {p['league']} | {p['market']}: {p['pick']} @ {p['odds']:.2f} | Tier: {p['tier']} | Conf: {p['confidence']}% | Reason: {p['reasoning'][:60] if p.get('reasoning') else 'N/A'}"
        for i, p in enumerate(picks)
    ])

    prompt = f"""# ELITE BETTING ANALYST PROMPT — 3-SLIP FRAMEWORK v1.0

## SYSTEM IDENTITY
You are APEX, an elite football betting analyst with 15 years of professional experience across European football, international fixtures, and continental competitions. You have a documented 71% long-term ROI and are known for ruthless discipline — you would rather output nothing than recommend a weak selection. Your job is not to find picks. Your job is to **protect capital first, grow it second.**

## INPUT FORMAT
Available picks list:
{picks_summary}

## PHASE 1 — PRE-SELECTION AUDIT (MANDATORY INTERNAL STEP)
Before building any slip, perform a silent audit of every pick:

### 1A. DISCARD IMMEDIATELY if any of the following apply:
- Odds below 1.20 (no value, juice too high)
- Confidence below 65%
- Tier C or below (unless Slip C requires it AND conf ≥ 70%)
- International friendly with no clear home/away context
- Any pick involving a team with <3 recent matches of form data
- Derby or rivalry match (unpredictable regardless of form)
- Pick reason mentions "historically strong" with no recent evidence
- Home team is in bottom 3 of their league (DO NOT BET AGAINST OR FOR)

### 1B. SCORE each surviving pick (internal use only):
Score = (Confidence% × 0.5) + (Tier_value × 20) + (Odds_value × 10)
Where: Tier_value: A=5, B+=4, B=3, C=2
Odds_value: 1.20–1.50=1, 1.51–1.80=2, 1.81–2.20=3, 2.21–3.00=4, 3.01+=5

Rank all surviving picks by Score descending. This is your **Master Ranked List**.

## PHASE 2 — SLIP CONSTRUCTION RULES

### ABSOLUTE LAWS (Violation = Invalid Output):
1. **No match appears in more than ONE slip** — this is the Iron Rule
2. **No pick number can be reused across slips**
3. **Each slip must contain picks from DIFFERENT matches**
4. **Minimum 3 picks per slip, Maximum 5 picks per slip**
5. **Combined odds must hit the target range for each slip**

### SLIP A — SAFETY NET (Target: 2.5x – 4.0x)
**Philosophy:** Near-certain outcomes. Protect the bankroll. Win rate 80%+.
- Use ONLY Tier A and B+ picks
- Minimum confidence: 78%
- Prefer odds in range 1.20 – 1.60
- Pick from the TOP of your Master Ranked List
- 3 picks preferred, 4 only if needed to reach 2.5x floor
- Avoid picking two picks from same competition (diversify)

### SLIP B — VALUE BALANCE (Target: 4.0x – 7.0x)
**Philosophy:** Solid selections with genuine value. Win rate 60–70%.
- Use Tier A, B+, or B picks
- Minimum confidence: 70%
- Prefer odds in range 1.50 – 2.00
- Must use DIFFERENT matches than Slip A
- 3–4 picks
- At least one pick from a different market type (BTTS or goals mixed with result)

### SLIP C — CALCULATED RISK (Target: 7.0x – 15.0x)
**Philosophy:** Maximum return with educated risk. Win rate 35–50%.
- Use Tier B+ and below if necessary, but conf ≥ 68%
- Prefer odds in range 1.80 – 3.50
- Must use DIFFERENT matches than Slip A AND Slip B
- 4–5 picks
- Avoid stacking >2 away wins in the same slip
- At least one pick should be a goals market (O/U or BTTS)
- **CRITICAL: DO NOT just stack draws or away picks. Diversify pick types:**
  - Maximum 1 draw pick per slip
  - Maximum 2 away win picks per slip
  - Include at least 1 home win or goals market pick
  - Mix different markets (1X2, BTTS, O/U, Handicap, Double Chance)

## PHASE 3 — FINAL VALIDATION CHECKLIST
Before outputting, verify:
- [ ] Zero match overlap between slips
- [ ] Slip A odds: 2.5x–4.0x
- [ ] Slip B odds: 4.0x–7.0x
- [ ] Slip C odds: 7.0x–15.0x
- [ ] Each slip has 3–5 picks
- [ ] All picks from Master Ranked List (no discarded picks)
- [ ] No two picks in any slip from the same match

## PHASE 4 — OUTPUT FORMAT
Output ONLY valid JSON. No explanation before or after. No markdown. No preamble.

{{
  "audit_summary": {{
    "total_picks_received": {len(picks)},
    "picks_discarded": 0,
    "picks_eligible": {len(picks)},
    "discard_reasons": []
  }},
  "master_ranked_list": [1, 2, 3, 4, 5],
  "slip_a": {{
    "picks": [1, 2, 3],
    "combined_odds": 3.25,
    "summary": "Three high-confidence picks from Tier A/B+ — diversified across competitions"
  }},
  "slip_b": {{
    "picks": [4, 5, 6],
    "combined_odds": 5.50,
    "summary": "Balanced mid-tier selections with market type diversification"
  }},
  "slip_c": {{
    "picks": [7, 8, 9, 10],
    "combined_odds": 9.40,
    "summary": "Higher-odds value picks with goals market for slip balance"
  }},
  "analyst_note": "Optional: flag any concern"
}}

## EDGE CASE HANDLING
- Not enough eligible picks for all 3 slips → Build what's possible, flag missing slips
- Combined odds can't hit target range → Adjust pick count (3–5 limit), note in analyst_note
- Two high-conf picks from same match → Pick the higher-scored one only
- All picks from same competition → Flag as "low diversity day"
- Fewer than 9 picks provided → Build Slip A + B only, flag Slip C as "insufficient picks"

## WHAT APEX NEVER DOES
- Never forces a pick just to fill a slip
- Never ignores the Iron Rule (match isolation between slips)
- Never uses a discarded pick
- Never outputs combined odds outside target range without flagging
- Never outputs partial JSON or broken formatting

*APEX — Analytical Precision, Extreme Discipline*"""

    ai_response = call_ai(prompt, max_tokens=1500)
    
    if ai_response:
        try:
            raw = ai_response.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").strip()
            if raw.startswith("json"):
                raw = raw[4:].strip()

            result = json.loads(raw)

            slip_a_picks = [picks[i-1] for i in result["slip_a"]["picks"] if i <= len(picks)]
            slip_b_picks = [picks[i-1] for i in result["slip_b"]["picks"] if i <= len(picks)]
            slip_c_picks = [picks[i-1] for i in result["slip_c"]["picks"] if i <= len(picks)]

            # Validate: remove duplicates across slips
            used_match_ids = set()
            for picks_list in [slip_a_picks, slip_b_picks, slip_c_picks]:
                to_remove = []
                for p in picks_list:
                    if p["match_id"] in used_match_ids:
                        to_remove.append(p)
                    else:
                        used_match_ids.add(p["match_id"])
                for p in to_remove:
                    picks_list.remove(p)

            # Ensure minimum picks per slip
            if len(slip_a_picks) < 2 or len(slip_b_picks) < 2 or len(slip_c_picks) < 2:
                logger.warning("AI returned insufficient picks, falling back to rule-based")
                return _generate_rule_based_slips(picks)

            return {
                "slip_a": {
                    "picks": slip_a_picks,
                    "combined_odds": _calc_combined(slip_a_picks),
                    "risk_level": "SAFE",
                    "summary": result["slip_a"].get("summary", "High confidence picks for steady returns"),
                },
                "slip_b": {
                    "picks": slip_b_picks,
                    "combined_odds": _calc_combined(slip_b_picks),
                    "risk_level": "MODERATE",
                    "summary": result["slip_b"].get("summary", "Balanced risk-reward selection"),
                },
                "slip_c": {
                    "picks": slip_c_picks,
                    "combined_odds": _calc_combined(slip_c_picks),
                    "risk_level": "HIGH",
                    "summary": result["slip_c"].get("summary", "High upside, calculated risk"),
                },
                "metadata": {
                    "total_picks_available": len(picks),
                    "generated_at": datetime.now().isoformat(),
                    "ai_generated": True,
                }
            }
        except Exception as e:
            logger.warning(f"Failed to parse AI response: {e}")

    return _generate_rule_based_slips(picks)


def _generate_rule_based_slips(picks: list[dict]) -> dict:
    """Fallback: Generate slips using rule-based selection with diverse matches and pick types."""

    picks_sorted = sorted(picks, key=lambda p: (p.get("confidence", 50) + (100 if p.get("tier") == "A" else 50 if p.get("tier") == "B+" else 0)), reverse=True)

    used_match_ids = set()

    # SLIP A - Safe: high confidence, low odds
    safe_picks = []
    for p in picks_sorted:
        if len(safe_picks) >= 4:
            break
        if p["match_id"] not in used_match_ids and p.get("confidence", 0) >= 65 and p.get("odds", 2) < 2.0:
            safe_picks.append(p)
            used_match_ids.add(p["match_id"])

    # SLIP B - Moderate: balanced odds, diverse markets
    moderate_picks = []
    moderate_markets = set()
    for p in picks_sorted:
        if len(moderate_picks) >= 4:
            break
        if p["match_id"] not in used_match_ids and p.get("odds", 1.5) >= 1.50 and p.get("odds", 3) < 3.0:
            # Try to diversify markets
            market = p.get("market", "")
            if len(moderate_picks) < 2 or market not in moderate_markets or len(moderate_markets) >= 2:
                moderate_picks.append(p)
                used_match_ids.add(p["match_id"])
                moderate_markets.add(market)

    # SLIP C - High: diverse pick types, NOT just draws/away
    high_picks = []
    draw_count = 0
    away_count = 0
    for p in picks_sorted:
        if len(high_picks) >= 5:
            break
        if p["match_id"] not in used_match_ids and p.get("odds", 1.5) >= 1.80:
            pick_lower = p.get("pick", "").lower()
            # Limit draws to max 1
            if "draw" in pick_lower and draw_count >= 1:
                continue
            # Limit away wins to max 2
            if "away" in pick_lower and away_count >= 2:
                continue
            high_picks.append(p)
            used_match_ids.add(p["match_id"])
            if "draw" in pick_lower:
                draw_count += 1
            if "away" in pick_lower:
                away_count += 1

    return {
        "slip_a": {
            "picks": safe_picks,
            "combined_odds": _calc_combined(safe_picks),
            "risk_level": "SAFE",
            "summary": f"{len(safe_picks)} high-confidence picks from different matches",
        },
        "slip_b": {
            "picks": moderate_picks,
            "combined_odds": _calc_combined(moderate_picks),
            "risk_level": "MODERATE",
            "summary": f"{len(moderate_picks)} balanced value picks with diverse markets",
        },
        "slip_c": {
            "picks": high_picks,
            "combined_odds": _calc_combined(high_picks),
            "risk_level": "HIGH",
            "summary": f"{len(high_picks)} diverse higher-odds picks (max 1 draw, max 2 away)",
        },
        "metadata": {
            "total_picks_available": len(picks),
            "generated_at": datetime.now().isoformat(),
            "ai_generated": False,
        }
    }


def shuffle_single_slip(
    slip_type: str, 
    current_slips: dict, 
    all_matches: list[dict],
    target_odds_min: float = None,
    target_odds_max: float = None
) -> dict:
    """
    Shuffle a single slip while keeping other slips intact.
    
    Args:
        slip_type: "slip_a", "slip_b", or "slip_c"
        current_slips: Current slips dict
        all_matches: All available matches with predictions
        target_odds_min/max: Override target odds range
    
    Returns:
        Updated slips dict with new selection for the specified slip
    """
    targets = {
        "slip_a": {"min": 2.5, "max": 4.0, "risk": "SAFE"},
        "slip_b": {"min": 4.0, "max": 7.0, "risk": "MODERATE"},
        "slip_c": {"min": 7.0, "max": 15.0, "risk": "HIGH"},
    }
    
    target = targets.get(slip_type, targets["slip_b"])
    min_odds = target_odds_min or target["min"]
    max_odds = target_odds_max or target["max"]
    risk = target["risk"]
    
    other_slip_match_ids = set()
    for key in ["slip_a", "slip_b", "slip_c"]:
        if key != slip_type and key in current_slips:
            for pick in current_slips[key].get("picks", []):
                other_slip_match_ids.add(pick.get("match_id"))
    
    available_picks = []
    for match in all_matches:
        if match.get("match_id") in other_slip_match_ids:
            continue
        match_date = match.get("match_date", "")
        for pred in match.get("predictions", []):
            available_picks.append({
                "match_id": match.get("match_id"),
                "home": match.get("home_team"),
                "away": match.get("away_team"),
                "league": match.get("league", ""),
                "time": match_date[11:16] if len(match_date) > 11 else "TBD",
                "date": match_date[:10] if len(match_date) >= 10 else "",
                "market": pred.get("market"),
                "pick": pred.get("pick"),
                "odds": pred.get("odds", 1.85),
                "confidence": pred.get("confidence", 75),
                "tier": pred.get("risk_tier", "B"),
                "reasoning": pred.get("reasoning", ""),
            })
    
    if not available_picks:
        return current_slips
    
    new_picks = _select_picks_for_target(
        available_picks, 
        min_odds, 
        max_odds,
        risk
    )
    
    new_slip = {
        "picks": new_picks,
        "combined_odds": _calc_combined(new_picks),
        "risk_level": risk,
        "summary": f"Shuffled selection targeting {min_odds:.1f}-{max_odds:.1f}x",
    }
    
    result = dict(current_slips)
    result[slip_type] = new_slip
    result["metadata"]["generated_at"] = datetime.now().isoformat()
    
    return result


def _select_picks_for_target(
    picks: list[dict],
    min_odds: float,
    max_odds: float,
    risk_level: str
) -> list[dict]:
    """Select picks that combine to target odds range."""
    
    min_conf = {"SAFE": 60, "MODERATE": 50, "HIGH": 40}.get(risk_level, 50)
    
    if risk_level == "SAFE":
        sorted_picks = sorted(picks, key=lambda p: p.get("confidence", 0), reverse=True)
    elif risk_level == "HIGH":
        sorted_picks = sorted(picks, key=lambda p: p.get("odds", 1.5), reverse=True)
    else:
        sorted_picks = sorted(picks, key=lambda p: p.get("confidence", 0) * p.get("odds", 1.5), reverse=True)
    
    selected = []
    used_matches = set()
    current_combined = 1.0
    
    for pick in sorted_picks:
        if len(selected) >= 5:
            break
        if pick["match_id"] in used_matches:
            continue
        if pick.get("confidence", 0) < min_conf:
            continue
        
        odds = pick.get("odds", 1.5)
        if risk_level == "SAFE" and odds > 2.5:
            continue
        
        projected = current_combined * odds
        
        if projected > max_odds * 1.3:
            continue
        
        selected.append(pick)
        used_matches.add(pick["match_id"])
        current_combined = projected
        
        if current_combined >= min_odds and len(selected) >= 3:
            break
    
    if current_combined < min_odds and len(selected) < 5:
        for pick in sorted_picks:
            if pick["match_id"] not in used_matches:
                odds = pick.get("odds", 1.5)
                if risk_level == "SAFE" and odds > 3.0:
                    continue
                selected.append(pick)
                used_matches.add(pick["match_id"])
                current_combined *= odds
                if current_combined >= min_odds or len(selected) >= 5:
                    break
    
    return selected


def _calc_combined(picks: list[dict]) -> float:
    """Calculate combined odds."""
    if not picks:
        return 0.0
    result = 1.0
    for p in picks:
        result *= p.get("odds", 1.0)
    return round(result, 2)


def _empty_slips() -> dict:
    """Return empty slips structure."""
    return {
        "slip_a": {"picks": [], "combined_odds": 0, "risk_level": "SAFE", "summary": "No picks available"},
        "slip_b": {"picks": [], "combined_odds": 0, "risk_level": "MODERATE", "summary": "No picks available"},
        "slip_c": {"picks": [], "combined_odds": 0, "risk_level": "HIGH", "summary": "No picks available"},
        "metadata": {"total_picks_available": 0, "generated_at": datetime.now().isoformat(), "ai_generated": False}
    }


def format_slip_for_display(slip: dict, label: str) -> str:
    """Format a slip for display in admin panel."""
    picks = slip.get("picks", [])
    combined = slip.get("combined_odds", 0)
    risk = slip.get("risk_level", "MODERATE")
    summary = slip.get("summary", "")
    
    lines = [f"🎯 {label} ({risk})", f"📊 Combined: {combined:.2f}x"]
    if summary:
        lines.append(f"💡 {summary}")
    lines.append("-" * 30)
    
    for i, p in enumerate(picks, 1):
        lines.append(f"{i}. {p['home']} vs {p['away']}")
        lines.append(f"   {p['league']} | {p['time']}")
        lines.append(f"   {p['market']}: {p['pick']} @ {p['odds']:.2f}")
        if p.get('reasoning'):
            lines.append(f"   📝 {p['reasoning'][:60]}...")
        lines.append("")
    
    return "\n".join(lines)
