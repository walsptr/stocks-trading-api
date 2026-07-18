# AGENTS.md

# Indonesia Stock Trading Analysis Platform

## Overview

This project is a multi-agent stock analysis platform focused exclusively on the Indonesia Stock Exchange (IDX / BEI).

The primary objective is to screen all Indonesian stocks daily using technical analysis and produce ranked trading opportunities.

The initial version uses only one market data provider:

- Yahoo Finance
- Python `yfinance` library

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
              ┌──────────┴──────────┐
              ▼                     ▼
      AI Analyst Agent       Alert Agent
              │                     │
              ▼                     ▼
            REST API          Telegram Bot
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

- Download historical OHLCV
- Update latest candles
- Retry failed downloads
- Validate missing values
- Store raw market data

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
- ATR

Breakout

- Highest High 20
- Lowest Low 20

Optional

- RSI
- MACD
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
price_above_ma5

price_above_ma10

price_above_ma20

ma5_above_ma10

ma10_above_ma20

volume_spike

breakout_20

high_liquidity

positive_momentum
```

Output

```
{
    "price_above_ma5": true,
    "price_above_ma10": true,
    "volume_spike": false,
    "breakout_20": true
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

### BSJP (Buy Afternoon Sell Morning)

Conditions

```
price_above_ma5

price_above_ma10

ma5_above_ma10

ma10_above_ma20

positive_momentum

volume_spike

high_liquidity

breakout_20
```

Future strategies

- Swing Trading
- Trend Following
- Pullback
- Breakout
- Mean Reversion

Output

```
{
    strategy: "BSJP",
    passed: true
}
```

---

# 6. Scoring Agent

## Responsibility

Generate Technical Score.

Initial weights

| Rule | Weight |
|-------|--------|
| Price > MA5 | 10 |
| Price > MA10 | 10 |
| MA5 > MA10 | 10 |
| MA10 > MA20 | 15 |
| Positive Momentum | 10 |
| Volume Spike | 20 |
| Breakout | 15 |
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
```

Example

```
1

BBCA

95

Strong Buy
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

Example

> BBCA is trading above its short-term moving averages while maintaining a healthy MA alignment (MA5 > MA10 > MA20). The stock also recorded a significant volume spike and successfully broke above its 20-day high, indicating strong buying momentum. With a Technical Score of 94, it qualifies as a Strong Buy candidate for the BSJP strategy.

---

# 9. Alert Agent

## Responsibility

Notify users whenever new trading opportunities appear.

Notification Channel

Telegram Bot

Supported Alerts

- New Strong Buy candidate
- Strategy matched
- Breakout detected
- Volume spike detected
- Score upgrade
- Score downgrade

Example

```
🚀 Strong Buy Detected

Ticker : BBCA

Strategy : BSJP

Technical Score : 94

Reasons

✅ Above MA5

✅ Above MA10

✅ MA Alignment

✅ Breakout

✅ Volume Spike

✅ High Liquidity
```

---

# 10. API Agent

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

GET /alerts
```

---

# Future Agents

## Backtesting Agent

Evaluate historical strategy performance.

Metrics

- Win Rate
- Average Return
- Profit Factor
- Maximum Drawdown
- Sharpe Ratio

---

## Strategy Optimizer Agent

Automatically search for better parameters.

Examples

- MA5 → MA7
- MA20 → MA30
- Volume Ratio 1.5 → 2.0

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
- Profit/Loss
- Portfolio Performance

---

## Risk Management Agent

Generate

- Entry Price
- Stop Loss
- Take Profit
- Risk/Reward Ratio

---

# Design Rules

- Every agent has a single responsibility.
- Indicator calculations must happen only once.
- Strategies are configuration-driven.
- Rule Engine must remain strategy-independent.
- AI never generates trading signals without underlying technical data.
- Every recommendation must be reproducible from historical market data.
- All agents should support asynchronous execution.

---

# Long-Term Vision

The platform will evolve through the following stages:

1. Market Data Collection
2. Technical Indicator Engine
3. Rule Engine
4. Strategy Engine
5. Technical Scoring
6. AI Technical Analysis
7. Telegram Alerting
8. Backtesting
9. Strategy Optimization
10. Portfolio Management
11. AI Trading Assistant

The final goal is to build a transparent, explainable, and extensible AI-powered trading platform for the Indonesian stock market, where every recommendation is backed by measurable technical indicators and reproducible trading rules.
