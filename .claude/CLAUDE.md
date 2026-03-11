# Stonkers - Crypto Trading Bot Context

> A "vibe coded" crypto trading bot built as an exercise in coding agents. Work in progress - hasn't turned a profit yet but is a fun exploration.

## Quick Reference

| Item | Value |
|------|-------|
| **Exchange** | Alpaca (paper/live) |
| **Pairs** | ETH/USD, SOL/USD |
| **Timeframe** | 15m candles |
| **Dashboard** | http://localhost:3004 |
| **Database** | SQLite at `data/stonkers.db` |
| **Entry Point** | `python -m src.main` |

## Project Structure

```
stonkers/
├── src/                          # Main application code
│   ├── main.py                   # Entry point, trading loop
│   ├── config/settings.py        # Config loader with hot-reload
│   ├── connectors/alpaca.py      # Alpaca API integration
│   ├── data/
│   │   ├── database.py           # SQLite persistence
│   │   └── historical_data_manager.py
│   ├── models/
│   │   ├── candle.py             # OHLCV data model
│   │   ├── position.py           # Position lifecycle
│   │   └── signal.py             # Trading signals
│   ├── engine/
│   │   ├── trading_engine.py     # Main orchestrator
│   │   ├── risk_manager.py       # Risk constraints
│   │   ├── position_manager.py   # Position tracking
│   │   ├── paper_trader.py       # Simulation execution
│   │   ├── live_trader.py        # Real execution
│   │   ├── backtest.py           # Backtesting engine
│   │   └── reconciler.py         # Exchange sync
│   ├── strategies/               # Trading strategies
│   │   ├── base.py               # Abstract base class
│   │   ├── ema_rsi.py            # ✅ Enabled
│   │   ├── ema_crossover.py      # ✅ Enabled
│   │   ├── bollinger_squeeze.py  # ✅ Enabled
│   │   ├── rsi_divergence.py     # ✅ Enabled (best performer)
│   │   ├── vwap_mean_reversion.py # ✅ Enabled
│   │   ├── momentum_thrust.py    # ❌ Disabled
│   │   └── support_resistance_breakout.py # ❌ Disabled
│   ├── analysis/                 # Analysis utilities
│   └── dashboard.py              # Flask web dashboard
├── tests/                        # pytest unit tests
├── config/                       # Strategy parameter files
├── data/                         # SQLite DB, historical data
├── static/                       # PWA dashboard assets
├── docs/                         # Documentation
├── config.yaml                   # Main configuration
├── run_backtest.py               # Backtest runner
└── requirements.txt              # Python dependencies
```

## Enabled Strategies (5)

| Strategy | Logic | Recent Backtest |
|----------|-------|-----------------|
| **RSI Divergence** ⭐ | Catches reversals via price/RSI divergence | +8.04%, 43.9% win, 1.67 PF |
| **EMA Crossover** | Fast/slow EMA trend following | +4.67%, 40% win, 1.56 PF |
| **Bollinger Squeeze** | Volatility breakout after consolidation | +2.93%, 37.8% win, 1.25 PF |
| **VWAP Mean Reversion** | Revert to VWAP with volume confirmation | +2.56%, 37.3% win, 1.54 PF |
| **EMA + RSI** | Mean reversion with trend context | +1.65%, 54.7% win, 1.42 PF |

## Risk Management Settings

- **Max positions**: 5 concurrent
- **Position size**: 20% of account per trade
- **Stop loss**: 2%
- **Take profit**: 5%
- **Trailing stop**: 1.5%
- **Daily loss limit**: 5% (halts trading if hit)

## Key Commands

```bash
# Run paper trading
python -m src.main

# Run backtest (all strategies)
python run_backtest.py --all

# Run backtest (specific strategy)
python run_backtest.py --strategy rsi_divergence --pair ETH/USD --days 30

# Run tests
pytest tests/ -v

# Docker build & run
docker build -t stonkers .
docker run --env-file .env -p 3004:3004 stonkers
```

## Architecture Overview

### Trading Loop (60-second cycle)
1. Load/reload config if changed
2. Update market regime (trending/ranging)
3. Check daily loss limit
4. Check exits for open positions (SL/TP/trailing)
5. Run strategies → generate signals
6. Apply risk checks → execute entries
7. Record equity snapshot
8. Display status → sleep

### Key Design Patterns
- **Immutable models**: Position, Signal, Candle are frozen dataclasses
- **Database as truth**: Positions survive restarts
- **Strategy plug-and-play**: All inherit from `base.py`
- **Config hot-reload**: No restart needed for param changes
- **Paper/Live toggle**: Safe development flow

## Environment Variables

```bash
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
PAPER_TRADING=true  # optional override
```

## Database Schema (SQLite)

- **positions**: Open/closed position lifecycle
- **trades**: Closed trades for analysis
- **signals**: Generated entry signals
- **account_state**: Equity snapshots
- **equity_snapshots**: Historical P&L tracking
- **reconciliation_logs**: Exchange sync audit trail

## Common Development Tasks

### Adding a New Strategy
1. Create `src/strategies/your_strategy.py`
2. Inherit from `StrategyBase` in `base.py`
3. Implement `analyze(candles) -> Optional[Signal]`
4. Add to `config.yaml` under `strategies`
5. Run backtest to validate

### Tuning Strategy Parameters
1. Edit params in `config.yaml`
2. Bot auto-reloads (hot-reload)
3. Or run `python run_backtest.py --strategy <name>` to test

### Debugging a Strategy
- Each strategy has diagnostic output
- Check `src/strategies/<name>.py` for `_get_diagnostics()`
- Dashboard shows recent signals and reasoning

## Known Issues / Future Work

See `docs/NEXT_STEPS.md` for roadmap items including:
- Improved regime detection
- Multi-timeframe confirmation
- Portfolio optimization
- More exchange support

## File Quick Reference

| Need to... | Look at... |
|------------|------------|
| Change trading pairs | `config.yaml` → `trading.pairs` |
| Adjust risk limits | `config.yaml` → `risk_management` |
| Modify strategy params | `config.yaml` → `strategies.<name>` |
| Add new strategy | `src/strategies/` + `base.py` |
| Debug trading logic | `src/engine/trading_engine.py` |
| Check API integration | `src/connectors/alpaca.py` |
| View dashboard code | `src/dashboard.py` + `static/` |
| Run analysis | `src/analysis/` utilities |
