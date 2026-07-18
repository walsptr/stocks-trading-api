# AGENTS.md

# Indonesia Stock Swing Trading Analysis Platform

## Overview

This project is a multi-agent stock analysis platform focused exclusively on the Indonesia Stock Exchange (IDX / BEI).

The primary objective is to screen all Indonesian stocks daily using technical analysis and produce ranked **swing trading** opportunities — positions typically held from a few days up to a few weeks (not intraday, not overnight-only).

The initial version uses only one market data provider:

- Yahoo Finance
- Python `yfinance` library

Daily OHLCV data from yfinance is well-suited for this strategy, since swing trading decisions do not depend on intraday or real-time data.

The platform is designed to be modular, scalable, and AI-ready.

---

# High-Level Workflow

```
                   Yahoo Finance
                         │
                         ▼
               Universe Agent
                         │
                         ▼
            Market Data Collector
                         │
                         ▼
              Indicator Agent
                         │
                         ▼
                Rule Engine
                         │
                         ▼
              Strategy Engine
                         │
                         ▼
               Scoring Agent
                         │
                         ▼
               Ranking Agent
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
      AI Analyst    Risk Mgmt    Alert Agent
        Agent         Agent           │
              │          │            ▼
              ▼          ▼      Telegram Bot
            REST API ◄───┘
              │
              ▼
          Frontend
```

---

# Agent Principles

Every agent must:

- Have only one responsibility.
- Never calculate another agent's responsibility.
- Be independently testable.
- Be reusable by multiple strategies.
- Be stateless whenever possible.
- Communicate through services or events.

---

# 1. Universe Agent

## Responsibility

Maintain the complete list of Indonesian stock symbols.

## Data Source

Yahoo Finance ticker list (.JK)

Examples

```
BBCA.JK
BBRI.JK
TLKM.JK
ASII.JK
```

## Tasks

- Load all IDX symbols
- Add newly listed companies
- Mark delisted companies
- Store ticker metadata

Output

```
[
    "BBCA.JK",
    "BBRI.JK",
    "BMRI.JK"
]
```

---

# 2. Market Data Collector Agent

## Responsibility

Download daily market data from Yahoo Finance.

## Library

Python

```
yfinance
```

## Data Collected

- Open
- High
- Low
- Close
- Adj Close
- Volume

## Tasks

- Download historical OHLCV (minimum 250 trading days, to support MA200 and long lookback indicators)
- Update latest daily candle after market close
- Retry failed downloads
- Validate missing values
- Store raw market data

## Notes

Since the strategy is swing (not BSJP / intraday), data freshness only needs to be end-of-day. This removes the real-time data constraint that would otherwise require a paid data provider.

Output

Daily OHLCV dataset.

---

# 3. Indicator Agent

## Responsibility

Calculate all technical indicators.

Indicators are calculated only once and reused by every strategy.

## Indicators

Trend

- SMA 5
- SMA 10
- SMA 20
- SMA 50
- SMA 200

Volume

- Volume MA20
- Volume Ratio

Momentum

- Daily Change %
- ATR (14)
- RSI (14) — **required, not optional**, used for entry/exit timing
- MACD (12, 26, 9) — **required**, used for medium-term momentum confirmation

Breakout / Structure

- Highest High 20
- Lowest Low 20
- Higher Low detection (swing structure)

Optional

- VWAP
- Bollinger Band

Output

Complete indicator dataset.

---

# 4. Rule Engine Agent

## Responsibility

Convert indicators into reusable boolean rules.

Rules do not contain strategy logic.

Example

```
price_above_ma20

price_above_ma50

ma20_above_ma50

ma50_above_ma200

pullback_to_ma20

rsi_not_overbought        (RSI < 70)

rsi_not_oversold          (RSI > 30, used for exit/avoid weak reversals)

macd_bullish_crossover

higher_low_formed

positive_momentum

volume_confirmation       (volume above average on up-days)

high_liquidity

breakout_20
```

Output

```
{
    "ma20_above_ma50": true,
    "pullback_to_ma20": true,
    "rsi_not_overbought": true,
    "macd_bullish_crossover": false,
    "high_liquidity": true
}
```

---

# 5. Strategy Engine

## Responsibility

Combine reusable rules into trading strategies.

Every strategy is configurable.

No indicator calculations are allowed here.

---

## Strategy

### Swing Trend Following

Holding period target: **3–20 trading days**.

Entry Conditions

```
ma20_above_ma50

ma50_above_ma200        (trend filter, optional strictness toggle)

pullback_to_ma20

rsi_not_overbought

macd_bullish_crossover

positive_momentum

high_liquidity
```

Exit Conditions (explicit — swing requires exit logic, unlike a same-day BSJP flip)

```
ma20_below_ma50                 -> exit signal (trend weakening)

price_below_trailing_stop       -> exit signal (ATR-based, see Risk Management Agent)

rsi_extreme_overbought (>80)    -> partial take-profit signal
```

Future strategies

- Pullback (dedicated variant with tighter entry filter)
- Breakout Continuation
- Mean Reversion (range-bound stocks only, filtered out of trend-following universe)

Output

```
{
    strategy: "Swing Trend Following",
    passed: true,
    suggested_holding_days: "5-15"
}
```

---

# 6. Scoring Agent

## Responsibility

Generate Technical Score.

Weights (revised for swing horizon — trend quality and entry timing weighted higher than short-term volume spikes)

| Rule | Weight |
|-------|--------|
| MA20 > MA50 | 20 |
| MA50 > MA200 | 15 |
| Pullback to MA20 | 20 |
| RSI healthy (not overbought) | 10 |
| MACD bullish crossover | 10 |
| Positive Momentum | 10 |
| Volume Confirmation | 5 |
| High Liquidity | 10 |

Maximum Score

100

Classification

| Score | Rating |
|--------|---------|
| 90–100 | Strong Buy |
| 75–89 | Buy |
| 60–74 | Watchlist |
| <60 | Ignore |

---

# 7. Ranking Agent

## Responsibility

Sort every stock by Technical Score.

Output

```
Rank

Ticker

Score

Rating

Suggested Holding Period
```

Example

```
1

BBCA

92

Strong Buy

5-15 days
```

---

# 8. AI Analyst Agent

## Responsibility

Explain why a stock passed the screening.

This agent NEVER calculates indicators.

It only reads outputs from:

- Indicator Agent
- Rule Engine
- Strategy Engine
- Scoring Agent
- Risk Management Agent

Example

> BBCA is in a confirmed uptrend (MA20 > MA50 > MA200) and has pulled back to test its MA20 support, a classic swing entry zone. RSI at 52 shows healthy momentum without being overbought, and MACD just triggered a bullish crossover. With a Technical Score of 92, it qualifies as a Strong Buy candidate for the Swing Trend Following strategy, with a suggested holding period of 5-15 trading days and an ATR-based stop loss at 1,850.

---

# 9. Risk Management Agent

## Responsibility

Generate position-level risk parameters. Elevated in priority compared to the original design, since swing trades carry multi-day exposure risk that a same-day BSJP flip does not.

## Tasks

- Calculate ATR-based Stop Loss
- Calculate Take Profit levels (e.g. 1.5x / 2x / 3x risk)
- Calculate Risk/Reward Ratio
- Suggest position size based on account risk % (e.g. max 1-2% risk per trade)
- Flag trailing stop level as price moves in favor

Output

```
{
    "ticker": "BBCA",
    "entry": 9500,
    "stop_loss": 9250,
    "take_profit_1": 9900,
    "take_profit_2": 10200,
    "risk_reward_ratio": 2.1,
    "suggested_position_size_pct": 5
}
```

---

# 10. Alert Agent

## Responsibility

Notify users whenever new trading opportunities or portfolio events appear.

Notification Channel

Telegram Bot

## Frequency

Unlike a BSJP setup (which would require near-closing-time alerts), swing alerts only need to run **once per day, after market close**, since entries are evaluated on completed daily candles.

Supported Alerts

- New Strong Buy candidate
- Strategy matched
- Trend reversal warning (MA20 crossing below MA50 on a held position)
- Approaching stop loss
- Take profit target reached
- Score upgrade
- Score downgrade

Example

```
📈 Swing Buy Candidate

Ticker : BBCA

Strategy : Swing Trend Following

Technical Score : 92

Suggested Holding : 5-15 days

Reasons

✅ MA20 > MA50 > MA200

✅ Pullback to MA20

✅ RSI Healthy (52)

✅ MACD Bullish Crossover

✅ High Liquidity

Risk

Stop Loss : 9,250

Take Profit : 9,900 / 10,200

Risk/Reward : 2.1
```

---

# 11. API Agent

## Responsibility

Expose all platform data to frontend applications.

Endpoints

```
GET /stocks

GET /stocks/{symbol}

GET /ranking

GET /strategies

GET /strategies/{name}

GET /analysis/{symbol}

GET /risk/{symbol}

GET /alerts
```

---

# Future Agents

## Backtesting Agent

Evaluate historical strategy performance. Well-suited to swing trading since yfinance's daily historical data is sufficient — no intraday data required.

Metrics

- Win Rate
- Average Return
- Average Holding Period
- Profit Factor
- Maximum Drawdown
- Sharpe Ratio

---

## Strategy Optimizer Agent

Automatically search for better parameters.

Examples

- MA20 → MA25
- MA50 → MA60
- RSI overbought threshold 70 → 75
- ATR stop multiplier 1.5 → 2.0

Optimization methods

- Grid Search
- Bayesian Optimization
- Genetic Algorithm

---

## Portfolio Agent

Track user portfolios.

Features

- Holdings
- Average Price
- Unrealized/Realized Profit/Loss
- Portfolio Performance
- Open position aging (days held vs suggested holding period)

---

# Design Rules

- Every agent has a single responsibility.
- Indicator calculations must happen only once.
- Strategies are configuration-driven.
- Rule Engine must remain strategy-independent.
- AI never generates trading signals without underlying technical data.
- Every recommendation must be reproducible from historical market data.
- Every entry signal must be paired with an explicit exit/risk definition (stop loss, take profit) — no entry-only signals.
- All agents should support asynchronous execution.

---

# Long-Term Vision

The platform will evolve through the following stages:

1. Market Data Collection
2. Technical Indicator Engine
3. Rule Engine
4. Strategy Engine
5. Technical Scoring
6. Risk Management
7. AI Technical Analysis
8. Telegram Alerting
9. Backtesting
10. Strategy Optimization
11. Portfolio Management
12. AI Trading Assistant

The final goal is to build a transparent, explainable, and extensible AI-powered swing trading platform for the Indonesian stock market, where every recommendation is backed by measurable technical indicators, explicit risk parameters, and reproducible trading rules.
