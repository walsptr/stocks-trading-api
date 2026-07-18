# Indonesia Stock Trading Platform

The platform currently provides an auditable IDX security universe, daily Yahoo Finance OHLCV collection, persisted technical indicators, reusable rules and strategies, persisted technical scoring and ranking, and an HTTP application exposed on port `21235`.

## Stack

- Python 3.12, `uv`, FastAPI, Uvicorn, Typer, SQLAlchemy, Alembic
- PostgreSQL 17 through Docker Compose
- Yahoo Finance through `yfinance`
- Raw Open/High/Low/Close, Yahoo Adjusted Close, and Volume

## Setup

```bash
cp .env.example .env
uv sync --extra dev
./deploy.sh
```

`deploy.sh` rebuilds the application image from the current source, starts PostgreSQL, applies Alembic migrations, imports the committed universe when the database contains no securities, and starts the HTTP application.

After deployment:

```text
API:  http://localhost:21235
Docs: http://localhost:21235/docs
Health: http://localhost:21235/health
```

## Docker Lifecycle

Use the lifecycle scripts after editing application code:

```bash
./destroy.sh
./deploy.sh
```

`destroy.sh` removes the Compose containers and networks but preserves the named PostgreSQL volume. Existing universe and market data therefore survive a normal destroy/redeploy cycle.

Run CLI commands through one-shot application containers:

```bash
docker compose run --rm app universe list --active-only
docker compose run --rm app market update
docker compose run --rm app runs show UUID
docker compose run --rm app indicators rebuild
docker compose run --rm app indicators update
docker compose run --rm app indicator-runs show UUID
docker compose run --rm app rules rebuild
docker compose run --rm app rules update
docker compose run --rm app rule-runs show UUID
docker compose run --rm app strategies rebuild --strategy "Swing Trend Following"
docker compose run --rm app strategies update --strategy "Swing Trend Following"
docker compose run --rm app strategy-runs show UUID
docker compose run --rm app scores rebuild
docker compose run --rm app scores update
docker compose run --rm app score-runs show UUID
docker compose run --rm app rankings rebuild
docker compose run --rm app rankings update
docker compose run --rm app ranking-runs show UUID
docker compose run --rm app analyses rebuild
docker compose run --rm app analyses update
docker compose run --rm app analysis-runs show UUID
docker compose run --rm app alerts update
docker compose run --rm app alerts retry --limit 100
docker compose run --rm app alert-runs show UUID
docker compose run --rm app backtests run --strategy "Swing Trend Following" --from 2025-01-01 --to 2026-07-16
docker compose run --rm app backtests list
```

Inspect services with `docker compose ps`, `docker compose logs app`, and `docker compose logs db`.

For an intentional clean reset that permanently deletes PostgreSQL data, run:

```bash
docker compose down --volumes --remove-orphans
./deploy.sh
```

Do not use the volume-reset command for normal code redeployments.

The committed universe contains 863 IDX symbols from the CC0-licensed `kjhq/Indonesia-Stock-Symbols-and-Metadata` snapshot last updated September 20, 2025. Treat it as a reviewed input snapshot: import a newer CSV with the same contract to add symbols and mark missing symbols inactive.

## Commands

```bash
uv run stocks universe list --active-only
uv run stocks market bootstrap --years 5
uv run stocks market update
uv run stocks market retry --run-id UUID
uv run stocks runs show UUID
```

Collection uses batches of 25 symbols, four bounded workers, three attempts, exponential backoff, and a seven-day incremental overlap by default. Successful ticker data is retained when another ticker fails, and the CLI exits `1` for a partial or total collection failure.

## Technical Indicators

The Indicator Agent calculates and persists `technical-v3` values from raw daily OHLCV, including required RSI(14), MACD(12,26,9), and higher-low structure signals.

- SMA 5, 10, 20, 50, and 200
- Volume MA20 and Volume Ratio
- Daily Change %
- Wilder ATR 14
- Highest High and Lowest Low from the prior 20 sessions
- Average Traded Value 20

Use `indicators rebuild` for a full or date-filtered calculation. Use `indicators update` after market-data collection; it loads warmup history and rewrites only the recent overlap plus new dates. Early observations are stored with null values until each full rolling window is available.

## Rule Engine

The strategy-independent Rule Engine consumes stored candles and `technical-v3` indicators. Swing thresholds live in `config/rules-swing-v1.yaml`, and each result records both the formula version and configuration checksum.

```bash
docker compose run --rm app indicators rebuild
docker compose run --rm app rules rebuild
docker compose run --rm app indicators update
docker compose run --rm app rules update
```

Read the latest and historical rule results through the HTTP app:

```text
GET http://localhost:21235/rules/BBCA
GET http://localhost:21235/rules/BBCA/history?limit=100&before=2026-07-16
```

Rules preserve `null` when the required lookback input is unavailable. The current configuration uses Volume Ratio ≥ 1.5, prior-20-session close breakout, positive daily change, and Average Traded Value 20 ≥ IDR 10 billion.

## Strategy Engine

The active strategy is Swing Trend Following, configured in `config/strategies/swing-trend-following-v1.yaml`, with a 3-20 trading-day holding horizon. Legacy BSJP strategy, backtest, and optimizer configurations remain in the repository with `enabled: false` and `default: false`; they are excluded from the scheduler, API research flow, CLI defaults, and deployment configuration.

The Position Lifecycle Agent converts passed Swing signals into virtual positions. Entries use the next session open, TP1 realizes 50%, the remaining position uses a non-decreasing ATR trailing stop, and any still-open position exits at the twentieth trading session. Position state and events are available from `GET /positions`, `GET /positions/{symbol}`, and `GET /positions/{symbol}/events`.

```bash
docker compose run --rm app strategies rebuild --strategy "Swing Trend Following"
docker compose run --rm app strategies update --strategy "Swing Trend Following"
docker compose run --rm app strategy-runs show UUID
```

Read configured strategies and Swing Trend Following results through the HTTP app:

```text
GET http://localhost:21235/strategies
GET http://localhost:21235/strategies/Swing%20Trend%20Following/BBCA
GET http://localhost:21235/strategies/Swing%20Trend%20Following/BBCA/history?limit=100&before=2026-07-16
```

## Scoring Agent

The Scoring Agent consumes exact-version persisted Rule Engine results and never recalculates indicators or strategy outcomes. Its versioned configuration lives in `config/scoring/technical-v1.yaml`, and each stored result includes the configuration checksum plus per-rule score contributions.

The initial 100-point model assigns 10 points each to Price > MA5, Price > MA10, MA5 > MA10, Positive Momentum, and High Liquidity; 15 points each to MA10 > MA20 and Breakout 20; and 20 points to Volume Spike. Ratings are Strong Buy (90–100), Buy (75–89), Watchlist (60–74), and Ignore (0–59).

```bash
docker compose run --rm app scores rebuild
docker compose run --rm app scores update
docker compose run --rm app score-runs show UUID
```

Read latest and historical scores through the HTTP app:

```text
GET http://localhost:21235/scores/BBCA
GET http://localhost:21235/scores/BBCA/history?limit=100&before=2026-07-16
```

If any weighted rule is `null`, the persisted score and rating are both `null`; contributions still identify the unavailable rule and preserve the reproducible evaluation details.

## Ranking Agent

The Ranking Agent consumes exact-version persisted Swing technical scores and stores complete daily market snapshots. Stocks with null scores are excluded. Scores sort descending, equal scores use competition ranks such as `1, 1, 3`, and symbols sort alphabetically within a tie.

```bash
docker compose run --rm app rankings rebuild
docker compose run --rm app rankings update
docker compose run --rm app ranking-runs show UUID
```

Read the newest complete snapshot or select a date, rating, and bounded result limit:

```text
GET http://localhost:21235/ranking
GET http://localhost:21235/ranking?trading_date=2026-07-16&rating=Strong%20Buy&limit=50
```

Rating filters are applied after ranking, so returned items preserve their full-market ranks.

## Deterministic Analyst Agent

The Analyst Agent produces reproducible English explanations for ranked stocks scoring at least 60. It reads only persisted same-date indicators, Swing strategy results, rules, scores, ranks, and risk outputs. Missing upstream sections are marked unavailable, and the agent never invents signals or makes external AI calls.

Each record includes a narrative, ordered bullish and caution reasons, source availability, Swing strategy status, score, rating, rank, exact source versions, and an informational disclaimer.

```bash
docker compose run --rm app analyses rebuild
docker compose run --rm app analyses update
docker compose run --rm app analysis-runs show UUID
```

Read latest, historical, and daily API analysis results:

```text
GET http://localhost:21235/analysis/BBCA
GET http://localhost:21235/analysis/BBCA/history?limit=100&before=2026-07-16
GET http://localhost:21235/analysis?trading_date=2026-07-16&rating=Strong%20Buy&strategy_status=passed&limit=50
```

## Telegram Alert Agent

The Alert Agent persists one combined event per stock and trading date after market close for Strong Buy candidates, Swing matches, trend reversals, approaching stops, reached targets, and score changes. The first update establishes a baseline without sending historical notifications. Subsequent updates process missed dates sequentially and retry pending deliveries.

Configure a single Telegram destination without committing credentials:

```bash
export STOCKS_TELEGRAM_BOT_TOKEN='...'
export STOCKS_TELEGRAM_CHAT_ID='...'
```

```bash
docker compose run --rm app alerts rebuild --from 2026-07-01 --to 2026-07-16
docker compose run --rm app alerts update
docker compose run --rm app alerts retry --limit 100
docker compose run --rm app alert-runs show UUID
```

`alerts rebuild` creates historical records but never delivers them. Missing credentials leave events pending rather than failing the market pipeline.

```text
GET http://localhost:21235/alerts?delivery_status=pending&limit=100
GET http://localhost:21235/alerts/{id}
```

## Swing Trend Following Backtesting Agent

The Backtesting Agent evaluates exact-version persisted Swing Trend Following signals without recalculating rules or indicators. A passed signal enters at the next session open and follows the configured ATR stop, partial take-profit, trailing stop, trend-reversal, and maximum-holding lifecycle. The default model applies a 0.15% buy fee and 0.25% sell fee to an equal IDR 1,000,000 notional per completed trade.

```bash
docker compose run --rm app backtests run --strategy "Swing Trend Following" --from 2025-01-01 --to 2026-07-16
docker compose run --rm app backtests list --limit 20
docker compose run --rm app backtests show UUID
docker compose run --rm app backtests trades UUID --symbol BBCA.JK --limit 100
```

Persisted results include completed trades, unclosed signals, win rate, average returns, compounded return, profit factor, maximum drawdown, trade-return Sharpe, and per-symbol metrics.

```text
GET http://localhost:21235/backtests
GET http://localhost:21235/backtests/{id}
GET http://localhost:21235/backtests/{id}/metrics
GET http://localhost:21235/backtests/{id}/symbols
GET http://localhost:21235/backtests/{id}/trades?symbol=BBCA&limit=100&offset=0
```

Backtesting is manually invoked and is not part of the weekday update pipeline.

## Swing Trend Following Strategy Optimizer

The optimizer performs a deterministic 24-candidate grid search over the Swing strategy's
MA20 pullback tolerance, RSI overbought threshold, volume-confirmation ratio, and strict
MA50-above-MA200 trend filter. It consumes persisted `technical-v3` indicators and daily candles, then
splits available trading dates chronologically into 70% training and 30% validation.
Candidates need at least 30 completed validation trades and a non-null Sharpe ratio.

Optimization is manual and review-only. It persists every candidate plus the winning
candidate's validation trades and per-symbol metrics, but never modifies active rule or
strategy configuration.

```bash
docker compose run --rm app optimizations run --strategy "Swing Trend Following" --from 2025-01-01 --to 2026-07-16
docker compose run --rm app optimizations list --limit 20
docker compose run --rm app optimizations show UUID
docker compose run --rm app optimizations candidates UUID --limit 100
docker compose run --rm app optimizations candidate UUID CANDIDATE_ID
```

```text
GET http://localhost:21235/optimizations
GET http://localhost:21235/optimizations/{id}
GET http://localhost:21235/optimizations/{id}/winner
GET http://localhost:21235/optimizations/{id}/candidates?limit=100&offset=0
GET http://localhost:21235/optimizations/{id}/winner/trades?limit=100&offset=0
GET http://localhost:21235/optimizations/{id}/winner/symbols
```

`docs/cron.example` schedules weekday updates at 18:00 Asia/Jakarta. The collector derives the latest completed weekday conservatively; exchange-holiday calendar support is deferred.

## Universe CSV Contract

Required columns are `snapshot_date`, `symbol`, `idx_code`, and `issuer_name`. Optional columns are `board` and `sector`. Every symbol must be an uppercase Yahoo ticker ending in `.JK`, and all rows in a file must share one ISO snapshot date.

## Tests

```bash
uv run pytest
```

PostgreSQL integration tests run when Docker is available and skip otherwise. Live Yahoo calls are not part of deterministic tests; use a limited bootstrap for smoke testing:

```bash
uv run stocks market bootstrap --years 1 --symbol BBCA.JK --symbol TLKM.JK
```

## API Deployment

The backend HTTP application is exposed on port `21235`:

```text
API: http://localhost:21235
Docs: http://localhost:21235/docs
Health: http://localhost:21235/health
```

Deploy the API, PostgreSQL, and weekday scheduler with:

```bash
sudo -n ./deploy.sh
```

The API supports direct client access through the configured
`STOCKS_CORS_ORIGINS` value. This repository contains the backend application,
database migrations, scheduler, and operational deployment scripts.

## Local OHLCV Cache and Scheduler

PostgreSQL is the authoritative local OHLCV cache. Normal updates request Yahoo Finance
only for dates after each symbol's latest persisted candle. When the local cache already
covers the latest completed market date, the provider is not called for that symbol.

```bash
docker compose run --rm app market status
docker compose run --rm app market update
docker compose run --rm app market refresh --from 2026-07-01 --to 2026-07-16 --symbol BBCA.JK
```

Use `market refresh` only for explicit historical corrections. The `scheduler` container
runs the weekday pipeline at 18:00 Asia/Jakarta by default. Configure it with
`STOCKS_SCHEDULER_ENABLED`, `STOCKS_SCHEDULER_TIMEZONE`, `STOCKS_SCHEDULER_HOUR`, and
`STOCKS_SCHEDULER_MINUTE`. Bootstrap remains manual and backtesting/optimization are not
scheduled.

```text
GET /market-data/status
```
