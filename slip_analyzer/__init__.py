"""
Slip Analyzer — Hybrid AI Telegram Betting Slip Analyzer.
Two-layer architecture: deterministic logic + reasoning explanations.
"""
from .analyzer import analyze_slip, analyze_slip_with_events, get_match_names

__all__ = ["analyze_slip", "analyze_slip_with_events", "get_match_names"]
