# Alpaca Migration Complete ✅

Your trading bot has been successfully migrated from Binance to Alpaca.

## What Changed

### Files Modified
- ✅ [requirements.txt](requirements.txt) - Added `alpaca-py>=0.13.0`
- ✅ [src/config/default_config.yaml](src/config/default_config.yaml) - Updated to use Alpaca with `BTC/USD` and `ETH/USD`
- ✅ [.env.example](.env.example) - Updated for Alpaca credentials
- ✅ [src/data/fetcher.py](src/data/fetcher.py) - Now uses abstract `ExchangeConnector`
- ✅ [src/main.py](src/main.py) - Uses connector factory pattern

### Files Created
- ✅ [src/connectors/alpaca.py](src/connectors/alpaca.py) - New Alpaca connector
- ✅ [src/connectors/__init__.py](src/connectors/__init__.py) - Connector factory
- ✅ [test_alpaca_connection.py](test_alpaca_connection.py) - Smoke test script

### Files Unchanged (As Designed)
- ✅ All strategy files in `src/strategies/` - **No changes needed**
- ✅ `src/engine/paper_trader.py` - **No changes needed**
- ✅ `src/engine/risk_manager.py` - **No changes needed**
- ✅ `src/logging/trade_logger.py` - **No changes needed**
- ✅ `src/data/models.py` - **No changes needed**

## Architecture Improvements

The migration introduced a **factory pattern** for exchange connectors:

```python
# Before (hardcoded)
from src.connectors.binance import BinanceConnector
connector = BinanceConnector()

# After (factory pattern)
from src.connectors import create_connector
connector = create_connector('alpaca', paper_trading=True)
```

This makes it trivial to add new exchanges in the future!

## Next Steps

### 1. Get Alpaca Paper Trading Keys

1. Visit: https://app.alpaca.markets/signup
2. Create a **paper trading** account
3. Go to: https://app.alpaca.markets/paper/dashboard/overview
4. Generate API keys

### 2. Set Environment Variables

Create a `.env` file:

```bash
cp .env.example .env
```

Edit `.env` and add your keys:

```bash
ALPACA_API_KEY=your_paper_api_key_here
ALPACA_SECRET_KEY=your_paper_secret_key_here
```

### 3. Install Dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 4. Run Smoke Test

```bash
python3 test_alpaca_connection.py
```

You should see:
```
✅ ALL TESTS PASSED
```

### 5. Start Trading Bot

```bash
python3 -m src.main
```

## Key Differences: Binance vs Alpaca

| Feature | Binance | Alpaca |
|---------|---------|--------|
| **Symbol Format** | `BTC/USDT` | `BTC/USD` |
| **Base Currency** | USDT (Tether) | USD |
| **Paper Trading** | Testnet with fake money | Paper account with real data |
| **US Available** | ❌ No | ✅ Yes |
| **Leverage** | Available | Spot-only (no leverage) |
| **Data Feed** | Free | Free (IEX) or Paid (SIP) |

## Troubleshooting

### "Invalid API Key"
- Make sure you're using **paper trading** keys
- Don't use live trading keys
- Check environment variables are set: `echo $ALPACA_API_KEY`

### "Symbol not found"
- Alpaca uses `BTC/USD` format, not `BTCUSD` or `BTC/USDT`
- Check symbol is supported: https://docs.alpaca.markets/docs/crypto-trading

### "No data returned"
- Crypto data doesn't require authentication
- Check your date range isn't in the future
- Verify the symbol format

## Adding Another Exchange (Future)

Thanks to the factory pattern, adding a new exchange is simple:

1. Create `src/connectors/your_exchange.py` implementing `ExchangeConnector`
2. Add to factory in `src/connectors/__init__.py`:
   ```python
   elif exchange_name == "your_exchange":
       return YourExchangeConnector(paper_trading)
   ```
3. Update config YAML:
   ```yaml
   exchange:
     name: your_exchange
     paper_trading: true
   ```

**No strategy code changes required!**

## Testing Checklist

Before running live (even paper trading), verify:

- [ ] Smoke test passes: `python3 test_alpaca_connection.py`
- [ ] Bot connects to Alpaca: Check startup logs
- [ ] Strategies load: Should see 2 enabled strategies
- [ ] Data fetching works: Check debug logs for candle data
- [ ] Paper trades execute: Watch for signal generation
- [ ] Risk limits enforced: Verify position size calculations

## Support

- Alpaca Docs: https://docs.alpaca.markets/
- Alpaca Python SDK: https://github.com/alpacahq/alpaca-py
- Your bot's README: [README.md](README.md)

---

**Migration completed:** $(date)
**Exchange:** Alpaca
**Mode:** Paper Trading
**Strategies:** EMA+RSI, EMA Crossover (all original strategies preserved)
