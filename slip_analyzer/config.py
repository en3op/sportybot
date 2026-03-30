"""
Configuration constants for the Enhanced Football Slip Optimization AI.
Consistency scoring model, penalties/bonuses, tier thresholds, market generation.
"""

from dataclasses import dataclass, field


# =============================================================================
# MATCH CLASSIFICATION TIERS (Phase 1)
# =============================================================================

@dataclass
class MatchTiers:
    """Classification thresholds for match predictability."""
    # Tier A: High Predictability
    a_form_diff_min: float = 2.0  # min form score difference
    a_odds_max: float = 1.50  # favorite odds ceiling
    a_league_min: str = "top5"  # minimum league quality

    # Tier B: Moderate Predictability
    b_form_diff_min: float = 1.0
    b_odds_max: float = 2.00

    # Tier C: Low Predictability
    c_form_diff_min: float = 0.0

    # Tier D: Unpredictable (auto-skip)
    d_skip_keywords: list[str] = field(default_factory=lambda: [
        "friendly", "exhibition", "youth", "u19", "u20", "u21", "u23",
        "women", "reserve", "dead rubber", "testimonial",
    ])


MATCH_TIERS = MatchTiers()


# =============================================================================
# CONSISTENCY SCORING MODEL (Phase 3)
# =============================================================================

@dataclass
class PenaltyValues:
    """Penalty modifiers subtracted from base probability score."""
    draw_penalty: int = -30
    high_odds_penalty: int = -20  # odds > 1.80
    friendly_penalty: int = -25
    handicap_aggression: int = -15  # handicap -1.5 or greater
    cup_knockout: int = -10
    derby_rivalry: int = -10
    injury_rotation: int = -15
    dead_rubber: int = -15
    new_manager: int = -10


@dataclass
class BonusValues:
    """Bonus modifiers added to base probability score."""
    strong_home_advantage: int = 5  # >70% home win rate
    clear_form_diff: int = 5  # W4+ vs L3+
    low_odds_value: int = 5  # odds <= 1.35
    motivation_gap: int = 5  # one team desperate, other nothing to play for


PENALTIES = PenaltyValues()
BONUSES = BonusValues()


# =============================================================================
# DECISION THRESHOLDS (Phase 3)
# =============================================================================

@dataclass
class ConsistencyThresholds:
    """Score ranges for pick classification."""
    elite_min: int = 80  # 80-100: Elite Pick
    strong_min: int = 70  # 70-79: Strong Pick
    solid_min: int = 60  # 60-69: Solid Pick
    risky_min: int = 30  # 30-49: Risky Pick
    # Below 30: Unreliable — still included in high-risk slip
    min_viable_score: int = 0


CONSISTENCY = ConsistencyThresholds()


# =============================================================================
# SLIP CONSTRUCTION RULES (Phase 4)
# =============================================================================

@dataclass
class SlipTier:
    """Configuration for a single slip tier."""
    name: str
    emoji: str
    min_score: int
    max_individual_odds: float
    total_odds_target: tuple[float, float]
    pick_count: tuple[int, int]
    max_risk_stars: int
    bankroll_pct: str
    philosophy: str


SAFE_SLIP = SlipTier(
    name="SAFE", emoji="\U0001f512",
    min_score=0, max_individual_odds=2.00,
    total_odds_target=(2.0, 5.0), pick_count=(3, 8),
    max_risk_stars=5, bankroll_pct="3-5%",
    philosophy="Best picks from your slip, lowest individual risk",
)

MODERATE_SLIP = SlipTier(
    name="MODERATE", emoji="\u2696\ufe0f",
    min_score=0, max_individual_odds=3.00,
    total_odds_target=(3.0, 10.0), pick_count=(3, 8),
    max_risk_stars=5, bankroll_pct="2-3%",
    philosophy="Balanced risk/reward from your games",
)

HIGH_SLIP = SlipTier(
    name="HIGH", emoji="\U0001f680",
    min_score=0, max_individual_odds=5.00,
    total_odds_target=(5.0, 50.0), pick_count=(3, 8),
    max_risk_stars=5, bankroll_pct="1-2%",
    philosophy="High reward picks from your games — all or nothing",
)

SLIP_TIERS = [SAFE_SLIP, MODERATE_SLIP, HIGH_SLIP]

# Cross-slip rules
MAX_PICKS_PER_SLIP = 7
CORRELATION_ADJUSTMENT = 0.92  # multiply win prob by this factor
MIN_MARKET_ODDS = 1.10
MAX_MARKET_ODDS = 3.00


# =============================================================================
# MARKET GENERATION (Phase 2)
# =============================================================================

# Markets to generate for each match
MARKET_TEMPLATES = {
    # Primary Outcome
    "1": {"label": "Home Win (1)", "category": "result"},
    "2": {"label": "Away Win (2)", "category": "result"},
    "X": {"label": "Draw (X)", "category": "result"},
    "1X": {"label": "Double Chance (1X)", "category": "dc"},
    "X2": {"label": "Double Chance (X2)", "category": "dc"},
    "12": {"label": "Double Chance (12)", "category": "dc"},
    "DNB1": {"label": "DNB Home", "category": "dnb"},
    "DNB2": {"label": "DNB Away", "category": "dnb"},

    # Goals
    "O0.5": {"label": "Over 0.5 Goals", "category": "goals"},
    "U0.5": {"label": "Under 0.5 Goals", "category": "goals"},
    "O1.5": {"label": "Over 1.5 Goals", "category": "goals"},
    "U1.5": {"label": "Under 1.5 Goals", "category": "goals"},
    "O2.5": {"label": "Over 2.5 Goals", "category": "goals"},
    "U2.5": {"label": "Under 2.5 Goals", "category": "goals"},
    "O3.5": {"label": "Over 3.5 Goals", "category": "goals"},
    "U3.5": {"label": "Under 3.5 Goals", "category": "goals"},

    # BTTS
    "BTTS_Y": {"label": "BTTS Yes", "category": "btts"},
    "BTTS_N": {"label": "BTTS No", "category": "btts"},

    # Handicap
    "HCP_H05": {"label": "Home -0.5", "category": "hcp"},
    "HCP_A05": {"label": "Away +0.5", "category": "hcp"},
    "HCP_H10": {"label": "Home -1.0", "category": "hcp"},
    "HCP_A10": {"label": "Away +1.0", "category": "hcp"},
    "HCP_H15": {"label": "Home -1.5", "category": "hcp"},
    "HCP_A15": {"label": "Away +1.5", "category": "hcp"},
}

# Bet type risk baseline (used when estimating base probability)
BET_TYPE_BASELINE_PROB: dict[str, float] = {
    "1": 45.0, "2": 30.0, "X": 25.0,
    "1X": 70.0, "X2": 55.0, "12": 75.0,
    "DNB1": 50.0, "DNB2": 35.0,
    "O0.5": 90.0, "U0.5": 10.0,
    "O1.5": 75.0, "U1.5": 25.0,
    "O2.5": 55.0, "U2.5": 45.0,
    "O3.5": 30.0, "U3.5": 70.0,
    "BTTS_Y": 55.0, "BTTS_N": 45.0,
    "HCP_H05": 45.0, "HCP_A05": 55.0,
    "HCP_H10": 35.0, "HCP_A10": 65.0,
    "HCP_H15": 25.0, "HCP_A15": 75.0,
}

# Bet type aliases
BET_TYPE_ALIASES: dict[str, str] = {
    "home": "1", "home win": "1", "1": "1",
    "away": "2", "away win": "2", "2": "2",
    "draw": "X", "x": "X",
    "1x": "1X", "x2": "X2", "12": "12",
    "double chance 1x": "1X", "double chance x2": "X2",
    "dnb home": "DNB1", "dnb away": "DNB2", "dnb": "DNB1",
    "over 0.5": "O0.5", "o0.5": "O0.5", "over 1.5": "O1.5", "o1.5": "O1.5",
    "over 2.5": "O2.5", "o2.5": "O2.5", "over 3.5": "O3.5", "o3.5": "O3.5",
    "under 0.5": "U0.5", "u0.5": "U0.5", "under 1.5": "U1.5", "u1.5": "U1.5",
    "under 2.5": "U2.5", "u2.5": "U2.5", "under 3.5": "U3.5", "u3.5": "U3.5",
    "btts": "BTTS_Y", "btts yes": "BTTS_Y", "btts no": "BTTS_N",
    "gg": "BTTS_Y", "ng": "BTTS_N", "both teams to score": "BTTS_Y",
    "over 2.5 & btts": "O2.5",  # simplified
}


# =============================================================================
# KNOWN DERBY PAIRS
# =============================================================================

DERBY_PAIRS: list[tuple[str, str]] = [
    ("man city", "man united"), ("liverpool", "everton"), ("arsenal", "tottenham"),
    ("chelsea", "tottenham"), ("real madrid", "barcelona"), ("real madrid", "atletico madrid"),
    ("barcelona", "espanyol"), ("ac milan", "inter milan"), ("roma", "lazio"),
    ("juventus", "torino"), ("bayern munich", "borussia dortmund"), ("psg", "marseille"),
    ("ajax", "feyenoord"), ("benfica", "porto"), ("benfica", "sporting"),
    ("rangers", "celtic"), ("river plate", "boca juniors"), ("flamengo", "vasco"),
    ("galatasaray", "fenerbahce"), ("besiktas", "galatasaray"),
]


# =============================================================================
# OUTPUT LIMITS
# =============================================================================

MAX_TELEGRAM_CHARS = 4000
MAX_MATCHES_TO_ANALYZE = 10
MIN_MATCHES_REQUIRED = 3
