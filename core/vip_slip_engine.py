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
    """Use AI to intelligently select picks for each slip tier."""
    
    picks_summary = "\n".join([
        f"{i+1}. {p['home']} vs {p['away']} | {p['league']} | {p['market']}: {p['pick']} @ {p['odds']:.2f} | Tier: {p['tier']} | Conf: {p['confidence']}% | {p['reasoning'][:50] if p.get('reasoning') else 'No reasoning'}..."
        for i, p in enumerate(picks)
    ])
    
    prompt = f"""You are an elite football betting analyst. Select the BEST picks for 3 different VIP betting slips.

AVAILABLE PICKS:
{picks_summary}

YOUR TASK:
Create exactly 3 slips with these targets:
- SLIP A (SAFE): Target combined odds 2.5-4.0x. 3-5 picks. Focus on high confidence (80%+), low risk.
- SLIP B (MODERATE): Target combined odds 4.0-7.0x. 3-5 picks. Balance value and risk.
- SLIP C (HIGH): Target combined odds 7.0-15.0x. 3-5 picks. Higher odds, calculated risks.

RULES:
1. Each slip MUST have different picks (no duplicates across slips)
2. Max 1 pick per match per slip
3. Prefer picks with solid reasoning
4. Consider tier quality (A > B+ > B > C)
5. Ensure combined odds fall within target range

OUTPUT FORMAT (JSON only, no markdown):
{{
  "slip_a": {{
    "picks": [1, 2, 3],
    "combined_odds": 3.25,
    "risk_level": "SAFE",
    "summary": "Brief explanation of slip strategy"
  }},
  "slip_b": {{
    "picks": [4, 5, 6],
    "combined_odds": 5.50,
    "risk_level": "MODERATE", 
    "summary": "Brief explanation of slip strategy"
  }},
  "slip_c": {{
    "picks": [7, 8, 9],
    "combined_odds": 10.0,
    "risk_level": "HIGH",
    "summary": "Brief explanation of slip strategy"
  }}
}}

IMPORTANT: 
- "picks" array contains the PICK NUMBERS from the list above (1, 2, 3, etc.)
- Make sure combined_odds is realistic (multiply the odds)
"""

    ai_response = call_ai(prompt, max_tokens=800)
    
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
    """Fallback: Generate slips using rule-based selection."""
    
    picks_sorted = sorted(picks, key=lambda p: p.get("confidence", 50), reverse=True)
    
    used_match_ids = set()
    
    safe_picks = []
    for p in picks_sorted:
        if len(safe_picks) >= 4:
            break
        if p["match_id"] not in used_match_ids and p.get("confidence", 0) >= 75:
            safe_picks.append(p)
            used_match_ids.add(p["match_id"])
    
    moderate_picks = []
    for p in picks_sorted:
        if len(moderate_picks) >= 4:
            break
        if p["match_id"] not in used_match_ids and p.get("odds", 1.5) >= 1.50:
            moderate_picks.append(p)
            used_match_ids.add(p["match_id"])
    
    high_picks = []
    for p in picks_sorted:
        if len(high_picks) >= 4:
            break
        if p["match_id"] not in used_match_ids and p.get("odds", 1.5) >= 2.0:
            high_picks.append(p)
            used_match_ids.add(p["match_id"])
    
    return {
        "slip_a": {
            "picks": safe_picks,
            "combined_odds": _calc_combined(safe_picks),
            "risk_level": "SAFE",
            "summary": "Top confidence picks for steady returns",
        },
        "slip_b": {
            "picks": moderate_picks,
            "combined_odds": _calc_combined(moderate_picks),
            "risk_level": "MODERATE",
            "summary": "Balanced risk-reward selection",
        },
        "slip_c": {
            "picks": high_picks,
            "combined_odds": _calc_combined(high_picks),
            "risk_level": "HIGH",
            "summary": "Higher odds for maximum returns",
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
