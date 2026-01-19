# Algo Trading Bot - Claude Code Build Instructions

## Project Overview

Build a modular, paper-trading-first algorithmic trading bot for cryptocurrency markets. The system should prioritize:
- **Modularity**: Strategies are plug-and-play, easy to add/modify
- **Observability**: Rich logging that explains *why* every decision was made
- **Safety**: Paper trading by default, risk management enforced
- **Iteration**: Easy backtesting to validate strategies before live deployment

**Target deployment**: Mac Mini (Apple Silicon), Python 3.11+

---

## Phase 1: Project Foundation

### Goal
Set up project structure, configuration system, and basic connectivity to Binance testnet.

### Tasks

#### 1.1 Project Structure
Create the following directory structure:
```
algo-trader/
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py         # Config loader
│   │   └── default_config.yaml # Default configuration
│   ├── connectors/
│   │   ├── __init__.py
│   │   ├── base.py             # Abstract exchange interface
│   │   └── binance.py          # Binance implementation via ccxt
│   ├── data/
│   │   ├── __init__.py
│   │   ├── fetcher.py          # OHLCV data fetching
│   │   ├── models.py           # Data classes (Candle, Trade, Signal)
│   │   └── storage.py          # SQLite persistence
│   ├── strategies/
│   │   ├── __init__.py
│   │   └── base.py             # Abstract strategy interface
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── paper_trader.py     # Paper trading execution
│   │   └── risk_manager.py     # Position sizing, limits
│   └── logging/
│       ├── __init__.py
│       └── trade_logger.py     # Decision logging
├── configs/                    # User strategy configs
│   └── example_strategy.yaml
├── data/                       # SQLite databases, downloaded data
├── logs/                       # Trade logs, session reports
├── tests/
│   └── __init__.py
├── requirements.txt
├── pyproject.toml
└── README.md
```

#### 1.2 Dependencies (requirements.txt)
```
ccxt>=4.0.0
pandas>=2.0.0
numpy>=1.24.0
ta>=0.10.0
pyyaml>=6.0
python-dotenv>=1.0.0
rich>=13.0.0
sqlalchemy>=2.0.0
aiosqlite>=0.19.0
asyncio>=3.4.3
pytest>=7.0.0
pytest-asyncio>=0.21.0
```

#### 1.3 Configuration System
Create a YAML-based configuration system that supports:
- Exchange credentials (API key, secret) loaded from environment variables
- Trading pairs to monitor
- Timeframes (1m, 5m, 15m, 1h, etc.)
- Strategy selection and parameters
- Risk management settings
- Logging verbosity

Example `default_config.yaml`:
```yaml
exchange:
  name: binance
  testnet: true  # ALWAYS true until explicitly changed
  
trading:
  pairs:
    - BTC/USDT
    - ETH/USDT
  default_timeframe: 15m
  
paper_trading:
  enabled: true  # ALWAYS true until explicitly changed
  starting_balance: 10000  # USDT
  
risk:
  max_position_pct: 0.1      # Max 10% of account per trade
  max_daily_loss_pct: 0.05   # Stop trading if down 5% for day
  max_open_positions: 3
  default_leverage: 1        # NO leverage by default
  
logging:
  level: INFO
  log_signals: true          # Log every signal generated
  log_decisions: true        # Log why trades were/weren't taken
  log_to_file: true
```

#### 1.4 Data Models
Create dataclasses for:
- `Candle`: timestamp, open, high, low, close, volume
- `Signal`: timestamp, pair, direction (LONG/SHORT/NEUTRAL), strength (0-1), strategy_name, reasoning (string)
- `Trade`: id, timestamp, pair, direction, entry_price, exit_price, quantity, pnl, strategy_name
- `Position`: pair, direction, entry_price, quantity, unrealized_pnl

#### 1.5 Exchange Connector
Implement Binance connector using ccxt:
- Async methods for fetching OHLCV data
- Method to get current price
- Method to get account balance (paper or real)
- Testnet URL configuration
- Rate limiting handling

#### 1.6 Basic Data Fetcher
Create a fetcher that:
- Pulls historical OHLCV data for backtesting
- Streams live candles for paper trading
- Stores data in SQLite for offline analysis
- Handles reconnection gracefully

### Success Criteria for Phase 1
- [ ] Running `python -m src.main` connects to Binance testnet
- [ ] Can fetch last 100 candles for BTC/USDT on 15m timeframe
- [ ] Candles are stored in SQLite database
- [ ] Config can be modified via YAML and changes take effect
- [ ] Rich logging shows connection status and data fetching

---

## Phase 2: Strategy Framework

### Goal
Build the abstract strategy interface and implement 3-4 starter strategies.

### Tasks

#### 2.1 Abstract Strategy Interface
Create `strategies/base.py` with:
```python
from abc import ABC, abstractmethod
from typing import Optional
from src.data.models import Candle, Signal

class Strategy(ABC):
    """Base class for all trading strategies."""
    
    name: str  # Unique identifier
    description: str  # Human-readable description
    required_history: int  # Minimum candles needed
    
    @abstractmethod
    def configure(self, params: dict) -> None:
        """Load strategy-specific parameters from config."""
        pass
    
    @abstractmethod
    def analyze(self, candles: list[Candle]) -> Optional[Signal]:
        """
        Analyze candles and optionally generate a signal.
        
        MUST include reasoning in the Signal explaining WHY
        the signal was generated (or why not, via logging).
        """
        pass
    
    @abstractmethod
    def get_default_params(self) -> dict:
        """Return default parameters for this strategy."""
        pass
```

#### 2.2 Implement Starter Strategies

**Strategy 1: EMA + RSI Mean Reversion** (`strategies/ema_rsi.py`)
- Parameters: ema_period (default 100), rsi_period (default 14), rsi_oversold (default 30), rsi_overbought (default 70)
- Logic: 
  - LONG when price < EMA AND RSI crosses above oversold
  - SHORT when price > EMA AND RSI crosses below overbought
- Exit: RSI returns to neutral zone (40-60)

**Strategy 2: EMA Crossover** (`strategies/ema_crossover.py`)
- Parameters: fast_ema (default 9), slow_ema (default 21)
- Logic:
  - LONG when fast EMA crosses above slow EMA
  - SHORT when fast EMA crosses below slow EMA
- Exit: Opposite crossover

**Strategy 3: Bollinger Band Squeeze** (`strategies/bollinger_squeeze.py`)
- Parameters: bb_period (default 20), bb_std (default 2), squeeze_threshold (default 0.05)
- Logic:
  - Detect squeeze: bandwidth < threshold
  - LONG on breakout above upper band after squeeze
  - SHORT on breakout below lower band after squeeze
- Exit: Price returns inside bands

**Strategy 4: RSI Divergence** (`strategies/rsi_divergence.py`)
- Parameters: rsi_period (default 14), lookback (default 10)
- Logic:
  - Bullish divergence: price makes lower low, RSI makes higher low
  - Bearish divergence: price makes higher high, RSI makes lower high
- Exit: RSI reaches opposite extreme

#### 2.3 Strategy Registry
Create a registry that:
- Auto-discovers strategies in the strategies folder
- Allows enabling/disabling strategies via config
- Supports running multiple strategies simultaneously

#### 2.4 Strategy Configuration
Each strategy should be configurable via YAML:
```yaml
strategies:
  ema_rsi:
    enabled: true
    params:
      ema_period: 100
      rsi_period: 14
      rsi_oversold: 30
      rsi_overbought: 70
  ema_crossover:
    enabled: true
    params:
      fast_ema: 9
      slow_ema: 21
```

### Success Criteria for Phase 2
- [ ] All 4 strategies implemented and follow the interface
- [ ] Each strategy can be enabled/disabled via config
- [ ] Each strategy's parameters can be tuned via config
- [ ] Running analysis produces Signals with clear reasoning
- [ ] Unit tests cover strategy logic

---

## Phase 3: Paper Trading Engine

### Goal
Build the execution engine that processes signals and simulates trades.

### Tasks

#### 3.1 Paper Trading Engine
Create `engine/paper_trader.py`:
- Maintains virtual balance and positions
- Processes Signals into Trade decisions
- Simulates realistic fills (with configurable slippage)
- Tracks open positions and P&L
- Persists state to SQLite (survives restarts)

Key methods:
- `execute_signal(signal: Signal) -> Optional[Trade]`
- `close_position(pair: str, reason: str) -> Trade`
- `get_portfolio_value() -> float`
- `get_open_positions() -> list[Position]`

#### 3.2 Risk Manager
Create `engine/risk_manager.py`:
- Position sizing based on account % risk
- Enforces max position limits
- Tracks daily P&L and enforces daily loss limit
- Validates trades before execution
- Calculates stop-loss and take-profit levels

Key methods:
- `calculate_position_size(signal: Signal, account_value: float) -> float`
- `can_open_position(signal: Signal) -> tuple[bool, str]`  # Returns (allowed, reason)
- `check_daily_limit() -> tuple[bool, str]`

#### 3.3 Decision Logging
Create comprehensive logging in `logging/trade_logger.py`:
- Every Signal generated (with strategy reasoning)
- Every trade decision (taken or rejected, with reason)
- Position opens/closes with full context
- Risk manager decisions

Log format (JSON for parseability):
```json
{
  "timestamp": "2024-01-15T10:30:00Z",
  "event_type": "SIGNAL_GENERATED",
  "strategy": "ema_rsi",
  "pair": "BTC/USDT",
  "direction": "LONG",
  "strength": 0.75,
  "reasoning": "RSI crossed above 30 (was 28, now 32) while price 42150 is below EMA-100 at 42800",
  "indicators": {
    "rsi": 32,
    "ema_100": 42800,
    "price": 42150
  }
}
```

#### 3.4 Main Loop
Create the main trading loop that:
1. Fetches latest candles
2. Runs all enabled strategies
3. Collects and prioritizes signals
4. Passes signals through risk manager
5. Executes approved trades via paper trader
6. Logs everything
7. Sleeps until next candle

### Success Criteria for Phase 3
- [ ] Paper trader maintains accurate balance across restarts
- [ ] Trades are simulated with realistic slippage
- [ ] Risk manager blocks oversized positions
- [ ] Daily loss limit stops trading when hit
- [ ] Every decision is logged with full reasoning
- [ ] Can run for hours without errors

---

## Phase 4: Backtesting

### Goal
Build backtesting capability to validate strategies against historical data.

### Tasks

#### 4.1 Historical Data Downloader
Create utility to:
- Download months of historical OHLCV data
- Store efficiently in SQLite
- Support multiple pairs and timeframes
- Resume interrupted downloads

#### 4.2 Backtesting Engine
Create `engine/backtest.py`:
- Replays historical candles through strategies
- Uses same paper trader logic (no lookahead bias)
- Generates trade history
- Calculates performance metrics

#### 4.3 Performance Metrics
Calculate and report:
- Total return (%)
- Win rate (%)
- Profit factor (gross profit / gross loss)
- Max drawdown (%)
- Sharpe ratio
- Average trade duration
- Number of trades
- Best/worst trade

#### 4.4 Backtest Reports
Generate markdown reports:
```markdown
# Backtest Report: EMA_RSI Strategy
**Period**: 2023-01-01 to 2024-01-01
**Pair**: BTC/USDT
**Timeframe**: 15m

## Summary
| Metric | Value |
|--------|-------|
| Total Return | +15.3% |
| Win Rate | 58% |
| Profit Factor | 1.4 |
| Max Drawdown | -12.5% |
| Total Trades | 127 |

## Monthly Breakdown
...

## Trade Log
...
```

### Success Criteria for Phase 4
- [ ] Can download 1 year of historical data
- [ ] Backtest runs without lookahead bias
- [ ] Performance metrics are calculated correctly
- [ ] Markdown report is generated automatically
- [ ] Can compare multiple strategies on same data

---

## Phase 5: Analysis & Visualization

### Goal
Build tools to understand what happened and why.

### Tasks

#### 5.1 Trade Journal Generator
Create daily/weekly summary reports:
- Trades taken with entry/exit reasoning
- Signals that weren't acted on (and why)
- Risk manager interventions
- P&L summary

#### 5.2 CLI Dashboard
Using Rich library, create optional live display:
- Current positions
- Recent signals
- Daily P&L
- Active strategy status
- Can be disabled for headless operation

#### 5.3 Post-Session Analysis Scripts
Create scripts to answer:
- "Why did the bot buy BTC at 3am?"
- "What signals were generated but rejected?"
- "How did strategy X perform this week?"

### Success Criteria for Phase 5
- [ ] Can generate readable session summaries
- [ ] CLI shows live status when running
- [ ] Can query historical decisions by time/pair/strategy
- [ ] Analysis scripts answer common questions

---

## Phase 6: Polish & Safety

### Goal
Harden the system for reliable long-term operation.

### Tasks

#### 6.1 Error Handling
- Graceful handling of exchange disconnects
- Automatic reconnection with backoff
- Alert on critical errors (optional Slack/Discord webhook)

#### 6.2 Safety Checks
- Confirmation prompt before any non-testnet operation
- Environment variable for ENABLE_LIVE_TRADING (default false)
- Sanity checks on order sizes

#### 6.3 Documentation
- README with setup instructions
- Strategy documentation
- Configuration reference

### Success Criteria for Phase 6
- [ ] Bot recovers from network issues automatically
- [ ] Cannot accidentally trade real money
- [ ] New user can set up from README

---

## Implementation Notes

### Important Principles
1. **Paper trading is the default**. Live trading requires explicit opt-in.
2. **Log everything**. You can't debug what you can't see.
3. **No magic numbers**. Every parameter comes from config.
4. **Strategies explain themselves**. Signals include human-readable reasoning.
5. **Fail safely**. When in doubt, don't trade.

### Suggested Development Order
1. Start with Phase 1 completely before moving on
2. Test each phase thoroughly before proceeding
3. Keep a running instance in paper mode as you develop
4. Add strategies incrementally, backtest each one

### Testing Approach
- Unit tests for strategy logic (given these candles, expect this signal)
- Integration tests for paper trader (given these signals, expect these trades)
- End-to-end test with 1 hour of historical data

---

## Appendix: Binance Testnet Setup

1. Go to https://testnet.binancefuture.com
2. Create account (no real verification needed)
3. Get API key and secret from API Management
4. Set environment variables:
   ```bash
   export BINANCE_TESTNET_API_KEY="your_key"
   export BINANCE_TESTNET_SECRET="your_secret"
   ```
5. Testnet gives you fake USDT to trade with

---

## Quick Reference: Adding a New Strategy

1. Create `src/strategies/your_strategy.py`
2. Inherit from `Strategy` base class
3. Implement `configure()`, `analyze()`, `get_default_params()`
4. Add config section to your strategy YAML:
   ```yaml
   strategies:
     your_strategy:
       enabled: true
       params:
         your_param: value
   ```
5. Run backtest to validate
6. Enable in live paper trading