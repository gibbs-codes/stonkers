# 🎯 Final Setup Steps - You're Almost There!

## What's Fixed ✅

All Alpaca integration issues have been resolved:

1. **Symbol Format** - Config uses `BTC/USD`, connector converts to `BTCUSD` automatically
2. **DateTime Warnings** - Fixed deprecated `datetime.utcnow()` → `datetime.now(datetime.UTC)`
3. **Import Errors** - Binance connector now lazy-loaded
4. **Config System** - Fully exchange-agnostic

## What You Need To Do

### Step 1: Add Your Real Alpaca API Keys

Your `.env` file currently has placeholder values. You need to replace them with your **actual** Alpaca paper trading API keys.

1. **Get your keys:**
   - Go to: https://app.alpaca.markets/paper/dashboard/overview
   - Click "Generate New Key" (if you haven't already)
   - Copy both the **API Key** and **Secret Key**

2. **Update `.env` file:**

   Open `.env` and replace the placeholders:

   ```bash
   # BEFORE (placeholders - won't work)
   ALPACA_API_KEY=your_paper_api_key_here
   ALPACA_SECRET_KEY=your_paper_secret_key_here

   # AFTER (your actual keys)
   ALPACA_API_KEY=PKxxxxxxxxxxxxxxxxxxxxxx
   ALPACA_SECRET_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
   ```

   **Important:**
   - API Key starts with `PK` for paper trading
   - Secret Key is a long random string
   - Don't share these keys with anyone!

### Step 2: Test Connection

Once you've added your real keys:

```bash
./test.sh
```

You should see:
```
✅ ALL TESTS PASSED

Your Alpaca connection is working correctly!
```

### Step 3: Start Trading Bot

```bash
./run.sh
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

💰 Starting Balance: $10000.00
📈 Trading Pairs: BTC/USD, ETH/USD
⏱️  Timeframe: 15m
```

## Technical Details

### Symbol Format

Your configuration uses standard format `BTC/USD`, but Alpaca requires `BTCUSD` (no slash).

**This is handled automatically!** The connector converts:
- `BTC/USD` → `BTCUSD`
- `ETH/USD` → `ETHUSD`

So you can keep using `BTC/USD` in your config, and everything will work.

### What Happens When You Start

1. Bot loads config from `src/config/default_config.yaml`
2. Reads API keys from `.env` file
3. Creates Alpaca connector (paper trading mode)
4. Connects to Alpaca
5. Loads enabled strategies (EMA+RSI, EMA Crossover)
6. Starts trading loop:
   - Fetches latest 15-minute candles for BTC/USD and ETH/USD
   - Runs strategies on the data
   - Generates signals when conditions are met
   - Executes paper trades through risk manager
   - Logs everything to console and files

## Files You'll See After Running

```
data/
  └── trading.db          # SQLite database with all trades and candles

logs/
  ├── trading_20260119.log        # Human-readable log
  └── decisions_20260119.jsonl    # JSON log of all decisions
```

## Common Issues

### "unauthorized" error
- Your `.env` file still has placeholder values
- Solution: Add your real API keys from Alpaca dashboard

### "No data returned"
- Old issue - now fixed! Symbol format is correct.

### Can't see my API keys in Alpaca dashboard
- Make sure you're on the **Paper Trading** dashboard
- URL should be: `https://app.alpaca.markets/paper/dashboard/overview`
- Not the live trading dashboard

## Safety Reminders

- ✅ You're in **paper trading** mode - no real money
- ✅ Trading on Alpaca **testnet** - fake funds
- ✅ Risk limits are enforced (max 10% per trade, 5% daily loss)
- ✅ All decisions are logged for review

## Next Steps After Running

1. Watch the logs - see what signals are generated
2. Review trades in `data/trading.db`
3. Adjust strategy parameters in `src/config/default_config.yaml`
4. Enable more strategies (Bollinger Squeeze, RSI Divergence)
5. Once comfortable, consider building backtesting (Phase 4)

---

**You're ready!** Just add your real Alpaca API keys and run `./test.sh` to verify. 🚀
