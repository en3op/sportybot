# SportyBot — Agent Reference Guide

## Project Overview

SportyBot is a Telegram-based football betting slip analyzer with two bots:
- **Free Bot** (`free_bot.py`): Public-facing. Users upload slip screenshots → OCR → team matching → live SportyBet odds → 3 optimized slip variations (SAFE/MODERATE/HIGH).
- **VIP Bot** (`bot.py`): Premium subscribers. Daily curated picks combining SportyBet odds + SofaScore form data + elite edge scoring.

Supporting infrastructure: Flask admin dashboard (`app.py`), automated pipeline (`runner.py`, `core/`), prediction pool system, and self-learning grading.

## Architecture

```
User → Telegram → bot.py (VIP) / free_bot.py (Free)
                          │
                   ┌──────┴──────┐
                   ▼             ▼
         analysis_engine    slip_analyzer/
         (v1: risk+verdict) (v2: consistency+slips)
                   │             │
                   └──────┬──────┘
                          ▼
                sportybet_scraper.py  ←── Live odds from SportyBet API
                          │
                   ┌──────┴──────┐
                   ▼             ▼
          infra/api_gateway   research/cache/
          (rate limit,        (2-tier cache:
           circuit breaker,    memory + SQLite)
           retry, fallback)
                          │
                          ▼
                  core/pipeline.py  ←── Automated daily/weekly runs
                          │
              ┌───────────┼───────────┐
              ▼           ▼           ▼
          normalizer  scoring_engine  pool_manager
              │           │           │
              ▼           ▼           ▼
          ai_agent.py  ranker.py   grader.py
          (form/stats) (top picks) (self-learning)
```

## Module Reference

### Bot Layer
| File | Purpose | Key Functions |
|------|---------|---------------|
| `free_bot.py` | Free Telegram bot (OCR + live odds analysis) | `handle_photo`, `handle_analyze_text`, `_analyze_with_live_data`, `_extract_potential_teams`, `_match_teams_to_events` |
| `bot.py` | VIP Telegram bot (daily picks + slip optimization) | `cmd_safe`, `cmd_optimize`, `handle_photo`, `_build_daily_slip` |

### Analysis Engines
| File | Purpose | Key Functions |
|------|---------|---------------|
| `slip_analyzer/analyzer.py` | Orchestrator for slip analysis pipeline | `analyze_slip`, `analyze_slip_with_events`, `get_match_names` |
| `slip_analyzer/slip_parser.py` | Parse raw text/OCR into structured picks | `parse_slip`, `extract_match_names`, `_normalize_input`, `_parse_loose` |
| `slip_analyzer/consistency_engine.py` | Score picks 0-100 on consistency | `score_all_picks`, `_score_single_pick` |
| `slip_analyzer/rebuild_engine.py` | Build SAFE/MODERATE/HIGH slip tiers | `build_three_slips`, `build_three_slips_from_events` |
| `slip_analyzer/config.py` | All thresholds, tier configs, market templates | `SLIP_TIERS`, `CONSISTENCY`, `MARKET_TEMPLATES` |
| `slip_analyzer/formatter.py` | Format Telegram output (4000 char limit) | `format_telegram_message`, `format_event_slips_message` |
| `analysis_engine.py` | V1 intent-aware slip analyzer | `analyze_slip`, `classify_bet_risk`, `RiskLevel` |
| `elite_engine.py` | Elite edge scoring (1-10 scale, VIP only) | `analyze_match` |

### Data Layer
| File | Purpose | Key Functions |
|------|---------|---------------|
| `sportybet_scraper.py` | SportyBet API scraper (primary data source) | `fetch_upcoming_events`, `analyze_all_markets`, `analyze_all_markets_full`, `implied_prob` |
| `sofascore_scraper.py` | Playwright scraper for form/position data | `get_pregame_form` |
| `scraper.py` | Flashscore fixture scraper | `scrape_flashscore` |

### Infrastructure
| File | Purpose |
|------|---------|
| `infra/api_gateway.py` | Rate limiting + circuit breaker + retry + cache-first reads |
| `infra/rate_limiter.py` | Token bucket + sliding window rate limiters |
| `research/cache/match_cache.py` | 2-tier cache (memory + SQLite) with category-based TTLs |

### Core Pipeline (`core/`)
| File | Purpose |
|------|---------|
| `pipeline.py` | Main orchestrator: scrape → normalize → score → rank → generate slips |
| `ai_agent.py` | Expert research agent (API-Football form/goals/position) |
| `scoring_engine.py` | AI consistency scoring per market per match |
| `ranker.py` | Global match ranking, min_score filter, top N selection |
| `slip_generator.py` | Generate SAFE/MODERATE/HIGH slips from ranked picks |
| `pool_manager.py` | Prediction pool DB CRUD (matches, predictions, user_slips) |
| `slip_matcher.py` | Parse user slip text, cross-reference against prediction pool |
| `weekly_runner.py` | Monday: scrape 7 days → populate prediction pool |
| `daily_refresh.py` | 06:00/18:00: re-scrape odds, detect >15% movement |
| `grader.py` | Auto-grade finished matches → update accuracy stats (self-learning) |
| `history_tracker.py` | SQLite history for daily runs, win/loss per market, weight adjustment |

### Web Dashboard
| File | Purpose |
|------|---------|
| `app.py` | Flask admin dashboard (VIP management, picks approval, n8n webhooks) |
| `templates/*.html` | 6 HTML templates for the dashboard |

## Running the Project

```bash
# Free bot
python free_bot.py

# VIP bot
python bot.py

# Flask dashboard
python app.py

# Automated pipeline (run once)
python runner.py

# Automated pipeline (daily schedule)
python runner.py --schedule

# Weekly pool population
python runner.py --weekly
```

## Key Conventions

### Parsing Strategy (slip_parser.py)
The parser tries 4 strategies in order of specificity:
1. **Structured**: `Match: X vs Y | Pick: Z | Odds: N.NN`
2. **Match-Bet-Odds**: `Team A vs Team B - BetType @ Odds`
3. **Team-Bet-Odds**: `TeamName win @ Odds`
4. **Loose**: Any line with a decimal number (last resort, strict guards)

### OCR → Team Matching (free_bot.py)
When a photo is sent:
1. OCR via Tesseract (PSM 4, grayscale primary, binarized fallback)
2. `_extract_potential_teams()` filters UI noise (betslip labels, bonus text, promo elements)
3. `get_match_names()` extracts "Team vs Team" patterns
4. `find_matching_event()` matches pairs against SportyBet API (Jaccard similarity ≥ 0.6)
5. `_match_teams_to_events()` matches individual teams (similarity ≥ 0.5, substring check)
6. `analyze_all_markets_full()` gets ALL available plays per matched event
7. `build_three_slips_from_events()` builds 3 differentiated tiers

### Slip Tier Differentiation
- **SAFE**: Highest implied probability, odds ≤ 1.80. Picks Double Chance, Over 1.5 Goals.
- **MODERATE**: Best value plays, odds 1.20-2.50. Prefers 1X2 and goals markets.
- **HIGH**: Highest odds plays, odds 2.00-6.00. Prefers 1X2 straight results (underdogs, draws).

### API Gateway Pattern (infra/)
All external API calls go through `APIGateway`:
```
Cache hit? → Return cached
Circuit open? → Fallback to stale cache
Rate limit exceeded? → Wait or reject
→ Rotate API key
→ Execute with retry (exponential backoff)
→ Cache result
```

### Self-Learning System
1. `grader.py` auto-grades finished matches against pending predictions
2. `history_tracker.py` tracks win/loss per market type
3. `scoring_engine.py` adjusts weights based on historical accuracy
4. Flow: Predict → Wait for match → Grade → Update accuracy stats → Adjust weights → Next prediction uses updated weights

## Databases

| File | Tables | Purpose |
|------|--------|---------|
| `cache.db` | `cache_entries` | 2-tier match data cache (live_odds: 60s, form: 6h, etc.) |
| `vip_users.db` | `vip_users`, `messages_log` | VIP subscription management |
| `prediction_pool.db` | `matches`, `predictions`, `match_research`, `user_slips`, `accuracy_stats` | 7-day prediction pool |
| `history.db` | `daily_runs`, `match_results`, `market_accuracy`, `scoring_weights` | Historical tracking for self-learning |

## Configuration

### Match Tiers (config.py)
- Tier 1: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Champions League, Europa League, World Cup, Euros
- Tier 2: Eredivisie, Liga Portugal, Championship, MLS, Copa Libertadores, AFCON, Copa America, Saudi Pro League
- Tier 3: Everything else (higher penalties applied)

### Consistency Thresholds (config.py)
- min_viable_score: 0 (all picks used, never reject)
- SAFE min_score: 0, max_individual_odds: 2.00
- MODERATE min_score: 0, max_individual_odds: 3.00
- HIGH min_score: 0, max_individual_odds: 5.00

### Cache TTLs (match_cache.py)
- live_odds: 60s
- match_info: 1h
- form: 6h
- h2h: 6h
- injuries: 2h
- lineups: 2h
- historical: 24h

## Common Tasks

### Adding a new bet type market
1. Add pattern to `slip_parser.py` parsers (match_pattern, goals_pattern, btts_pattern, etc.)
2. Add market template to `config.py` `MARKET_TEMPLATES`
3. Add baseline probability to `config.py` `BET_TYPE_BASELINES`
4. Add scoring logic to `consistency_engine.py`

### Adding a new SportyBet market to scraper
1. Add marketId to `fetch_upcoming_events()` params in `sportybet_scraper.py`
2. Add parsing logic in the market loop
3. Add analysis in `analyze_all_markets_full()`

### Adjusting slip tier behavior
1. Edit criteria functions in `rebuild_engine.py`: `_safe_criteria`, `_moderate_criteria`, `_high_criteria`
2. Adjust odds caps and probability thresholds
3. Test with `analyze_slip_with_events()` using mock plays

### Improving OCR accuracy
1. Adjust preprocessing in `extract_text_from_image()` (threshold values, PSM mode)
2. Add noise patterns to `slip_parser.py` `SKIP_PATTERNS`
3. Add noise words to `free_bot.py` `_extract_potential_teams()` `skip_exact` / `skip_contains`

### Debugging matching failures
1. Check `bot.log` for OCR text and matching scores
2. Run extraction test: `python -c "from free_bot import _extract_potential_teams; print(_extract_potential_teams('your text'))"`
3. Check team normalization: `python -c "from free_bot import normalize_name; print(normalize_name('Team Name'))"`

## Known Issues & TODOs

1. **Exposed credentials**: Bot tokens and API keys are hardcoded. Should move to environment variables.
2. **No AGENTS.md until now**: Project had zero documentation.
3. **bot.py missing imports**: `extract_text_from_image` and `parse_slip_text` are used but never defined or imported.
4. **Two analysis engines**: `analysis_engine.py` (v1) and `slip_analyzer/` (v2) coexist. `free_bot.py` imports both but only uses v2.
5. **No test suite**: Zero automated tests for any module.
6. **OCR limitations**: Lower-league teams not in SportyBet API cannot be matched.
7. **Misnamed directories**: `C:UsersEN3OPDesktopsportybotstatic/` and `C:UsersEN3OPDesktopsportybottemplates/` are artifacts from a path bug.

## Dependencies

```
python-telegram-bot==21.6
pytesseract==0.3.13
Pillow==10.4.0
requests==2.32.3
flask>=3.0
playwright>=1.40
schedule>=1.2
```

System dependency: Tesseract OCR must be installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` (Windows) or in PATH.
