# Stonkers - Algorithmic Trading Bot

A modular, paper-trading-first algorithmic trading bot for cryptocurrency markets.

## Features

✅ **Modular Strategy System** - Plug-and-play strategies, easy to add/modify
✅ **Paper Trading** - Safe testing with simulated trades
✅ **Risk Management** - Position sizing, daily loss limits, max positions
✅ **Rich Logging** - Every decision is logged with reasoning
✅ **SQLite Persistence** - All trades, positions, and candles stored
✅ **4 Built-in Strategies** - EMA+RSI, EMA Crossover, Bollinger Squeeze, RSI Divergence

## Project Status

**Phase 1-3 Complete** ✅
- ✅ Project foundation and configuration
- ✅ Data models and storage
- ✅ Exchange connector architecture
- ✅ 4 trading strategies implemented
- ✅ Paper trading engine
- ✅ Risk management system
- ✅ Comprehensive logging

**Ready for:** Exchange connector integration (see below)

## Architecture

```
src/
├── config/          # YAML configuration system
├── connectors/      # Exchange connectors (pluggable)
├── data/            # Data models, storage, fetching
├── strategies/      # Trading strategies (modular)
├── engine/          # Paper trader, risk manager
└── logging/         # Decision and trade logging
```

## Quick Start

### 1. Install Dependencies

```bash
python3 -m pip install -r requirements.txt
```

### 2. Configure Exchange

The current implementation includes a Binance connector template. To use a different broker:

1. Implement a new connector in `src/connectors/` following the `ExchangeConnector` interface
2. Update `src/config/default_config.yaml` with your exchange name
3. Set up environment variables in `.env`

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Configure Strategies

Edit `src/config/default_config.yaml`:

```yaml
strategies:
  ema_rsi:
    enabled: true
    params:
      ema_period: 100
      rsi_period: 14
  ema_crossover:
    enabled: true
    params:
      fast_ema: 9
      slow_ema: 21
```

### 4. Run

```bash
python3 -m src.main
```

## Switching to a Different Brokerage

The system is designed to be broker-agnostic. To add a new exchange:

### Step 1: Create Exchange Connector

Create `src/connectors/your_broker.py`:

```python
from src.connectors.base import ExchangeConnector

class YourBrokerConnector(ExchangeConnector):
    async def connect(self) -> bool:
        # Your implementation
        pass

    async def fetch_ohlcv(self, pair, timeframe, since=None, limit=100):
        # Your implementation
        pass

    async def get_current_price(self, pair):
        # Your implementation
        pass

    async def get_balance(self, currency='USDT'):
        # Your implementation
        pass

    async def place_order(self, pair, side, order_type, amount, price=None):
        # Your implementation (for live trading)
        pass

    async def close(self):
        # Your implementation
        pass
```

### Step 2: Update Main

In `src/main.py`, replace:
```python
from src.connectors.binance import BinanceConnector
```
with:
```python
from src.connectors.your_broker import YourBrokerConnector
```

And update initialization:
```python
self.connector = YourBrokerConnector()
```

### Step 3: Update Config

In `src/config/default_config.yaml`:
```yaml
exchange:
  name: your_broker
  testnet: true
```

## Configuration Reference

### Risk Management

```yaml
risk:
  max_position_pct: 0.1      # Max 10% of account per trade
  max_daily_loss_pct: 0.05   # Stop if down 5% for the day
  max_open_positions: 3       # Max 3 concurrent positions
  default_leverage: 1         # No leverage by default
```

### Paper Trading

```yaml
paper_trading:
  enabled: true              # ALWAYS true until live tested
  starting_balance: 10000    # Starting capital (USDT)
```

### Logging

```yaml
logging:
  level: INFO                # DEBUG, INFO, WARNING, ERROR
  log_signals: true          # Log every signal generated
  log_decisions: true        # Log trade decisions
  log_to_file: true          # Write to log files
```

## Built-in Strategies

### 1. EMA + RSI Mean Reversion
- **Long**: Price below EMA AND RSI crosses above oversold
- **Short**: Price above EMA AND RSI crosses below overbought
- **Best for**: Range-bound markets with pullbacks

### 2. EMA Crossover
- **Long**: Fast EMA crosses above Slow EMA
- **Short**: Fast EMA crosses below Slow EMA
- **Best for**: Trending markets

### 3. Bollinger Band Squeeze
- **Long**: Breakout above upper band after squeeze
- **Short**: Breakout below lower band after squeeze
- **Best for**: Consolidation breakouts

### 4. RSI Divergence
- **Long**: Price lower low + RSI higher low (bullish divergence)
- **Short**: Price higher high + RSI lower high (bearish divergence)
- **Best for**: Trend exhaustion reversals

## Adding a New Strategy

1. Create `src/strategies/your_strategy.py`:

```python
from src.strategies.base import Strategy
from src.data.models import Signal, Direction

class YourStrategy(Strategy):
    name = "your_strategy"
    description = "Description of your strategy"
    required_history = 50

    def configure(self, params: dict) -> None:
        self.params = {**self.get_default_params(), **params}

    def get_default_params(self) -> dict:
        return {'param1': 10, 'param2': 20}

    def analyze(self, candles) -> Optional[Signal]:
        # Your strategy logic
        pass
```

2. Register in `src/strategies/registry.py`:
```python
from src.strategies.your_strategy import YourStrategy

_available_strategies = {
    'your_strategy': YourStrategy,
    # ... existing strategies
}
```

3. Enable in config:
```yaml
strategies:
  your_strategy:
    enabled: true
    params:
      param1: 15
      param2: 25
```

## Logs and Data

- **Logs**: `logs/trading_YYYYMMDD.log` - Human-readable logs
- **Decisions**: `logs/decisions_YYYYMMDD.jsonl` - JSON decision log
- **Database**: `data/trading.db` - SQLite database with candles, trades, positions

## Safety Features

🔒 **Paper trading is the default** - Must explicitly opt-in to live trading
🔒 **Daily loss limit** - Stops trading if max loss reached
🔒 **Position size limits** - Never risk more than configured percentage
🔒 **Max open positions** - Prevents over-exposure
🔒 **All decisions logged** - Full audit trail of why trades were made

## Next Steps

1. **Integrate your chosen brokerage** - Follow guide above
2. **Test strategies** - Run in paper mode, review decision logs
3. **Tune parameters** - Adjust strategy parameters based on results
4. **Phase 4: Backtesting** - Implement backtesting engine (see instructions.md)
5. **Phase 5: Analysis** - Build visualization and reporting tools
6. **Phase 6: Live trading** - Only after extensive paper trading

## Support

For issues or questions about the framework, see [instructions.md](instructions.md) for detailed build instructions.

## License

MIT License - Use at your own risk. This is educational software.

---

**⚠️ IMPORTANT**: This software is for educational purposes. Trading cryptocurrencies carries significant risk. Never trade with money you can't afford to lose. Always paper trade thoroughly before considering live trading.
