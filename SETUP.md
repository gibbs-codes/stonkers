# Quick Setup Guide

## Prerequisites

- Python 3.11+ (you have Python 3.13 ✅)
- Alpaca paper trading account

## 1. Clone & Navigate

```bash
cd /Users/james/code/gibbsCodesOrg/stonkers
```

## 2. Set Up Virtual Environment

The virtual environment is already created! Just activate it:

```bash
# Activate virtual environment
source venv/bin/activate

# Your prompt should now show (venv)
```

**All dependencies are already installed!** ✅

To deactivate later:
```bash
deactivate
```

## 3. Set Up Alpaca Credentials

1. Create Alpaca paper trading account: https://app.alpaca.markets/signup
2. Get API keys: https://app.alpaca.markets/paper/dashboard/overview
3. Create `.env` file:

```bash
cp .env.example .env
```

4. Edit `.env` with your keys:

```bash
ALPACA_API_KEY=PK...your_key_here
ALPACA_SECRET_KEY=...your_secret_here
```

## 4. Test Connection

```bash
# Make sure venv is activated!
source venv/bin/activate

# Run smoke test
python test_alpaca_connection.py
```

You should see:
```
✅ ALL TESTS PASSED
```

## 5. Run the Bot

```bash
# Make sure venv is activated!
source venv/bin/activate

# Start trading bot
python -m src.main
```

You should see:
```
🚀 STONKERS - Algorithmic Trading Bot
============================================================
Connecting to ALPACA...
⚠️  PAPER TRADING MODE - Using fake money
📄 PAPER TRADING ENGINE - No real orders
✅ Connected to exchange

📊 Loaded 2 strategies:
  • ema_rsi: EMA + RSI mean reversion strategy
  • ema_crossover: EMA crossover trend following strategy
...
```

## Daily Workflow

```bash
# 1. Navigate to project
cd /Users/james/code/gibbsCodesOrg/stonkers

# 2. Activate venv
source venv/bin/activate

# 3. Run the bot
python -m src.main

# 4. When done, deactivate (optional)
deactivate
```

## Troubleshooting

### "python: command not found"
Use `python3`:
```bash
python3 -m src.main
```

### "No module named 'alpaca'"
Activate the virtual environment:
```bash
source venv/bin/activate
```

### "Invalid API Key"
- Make sure you're using **paper trading** keys
- Check `.env` file exists and has correct keys
- Verify keys at: https://app.alpaca.markets/paper/dashboard/overview

### Check if venv is activated
Your terminal prompt should show `(venv)` at the beginning:
```bash
(venv) james@mac stonkers %
```

## What's Installed

All dependencies are in the virtual environment:

- ✅ `alpaca-py` - Alpaca API client
- ✅ `pandas` - Data analysis
- ✅ `numpy` - Numerical computing
- ✅ `ta` - Technical analysis indicators
- ✅ `pyyaml` - Configuration
- ✅ `python-dotenv` - Environment variables
- ✅ `rich` - Beautiful console output
- ✅ `sqlalchemy` - Database ORM
- ✅ `aiosqlite` - Async SQLite
- ✅ `pytest` - Testing

## Files Generated

When you run the bot, it will create:

```
data/
  └── trading.db         # SQLite database with candles, trades, positions

logs/
  ├── trading_YYYYMMDD.log        # Human-readable logs
  └── decisions_YYYYMMDD.jsonl    # JSON decision log
```

## Configuration

Edit [src/config/default_config.yaml](src/config/default_config.yaml) to:
- Change trading pairs
- Enable/disable strategies
- Adjust risk parameters
- Modify strategy parameters

## Next Steps

- Review [MIGRATION_SUMMARY.md](MIGRATION_SUMMARY.md) for full details
- Check [README.md](README.md) for architecture overview
- Add more strategies in `src/strategies/`
- Backtest strategies (Phase 4 - not yet implemented)

## Getting Help

- Alpaca Docs: https://docs.alpaca.markets/
- Alpaca Python SDK: https://github.com/alpacahq/alpaca-py
- Bot README: [README.md](README.md)
