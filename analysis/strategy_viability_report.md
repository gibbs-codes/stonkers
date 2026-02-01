# Strategy Viability Matrix (15m, 30-day window ending 2026-01-28)
Pairs: ETH/USD, SOL/USD | Initial balance: $1,000 | Days: 32
Scoring: frequency (trades/day), win rate, profit factor, max DD, Sharpe. Higher is better; thresholds per brief.

| Strategy | Trades/Day | Win% | PF | Max DD% | Sharpe | Score | Tier |
|---|---|---|---|---|---|---|---|
| EMA+RSI | 1.00 | 40.6% | 0.89 | 0.74 | -0.05 | 13 | 🟡 Monitor & Test |
| EMA_CROSS | 0.34 | 36.4% | 1.44 | 1.85 | 0.15 | 13 | 🟡 Monitor & Test |
| BB_SQUEEZE | 0.38 | 41.7% | 1.53 | 2.79 | 0.19 | 13 | 🟡 Monitor & Test |
| RSI_DIVERGENCE | 0.47 | 40.0% | 1.39 | 1.73 | 0.14 | 13 | 🟡 Monitor & Test |
| MOMENTUM_THRUST | 0.47 | 40.0% | 1.36 | 1.81 | 0.14 | 13 | 🟡 Monitor & Test |
| VWAP_MEAN_REV | 1.91 | 39.3% | 1.08 | 0.54 | 0.03 | 13 | 🟡 Monitor & Test |
| SR_BREAKOUT | 0.47 | 40.0% | 1.50 | 1.04 | 0.18 | 13 | 🟡 Monitor & Test |

## Red Flags (Kill/Shelve)
None — all strategies meet minimum viability thresholds.