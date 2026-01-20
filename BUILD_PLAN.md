# STONKERS v2 - Battle-Tested Build Plan

## Lessons Learned from v1 (The Hard Way)

### Critical Bugs We Hit Today
1. **Duplicate positions** - Risk manager checked count, not if pair already had position
2. **Timezone chaos** - Mixed naive and aware datetimes crashed on subtraction
3. **Wrong timestamps** - Used candle time instead of actual trade time (25 hour "trades"!)
4. **Immediate exit loop** - Multiple strategies fired in same iteration, opening then closing
5. **KeyError crashes** - No validation when price fetch failed
6. **Stale data** - Same candle analyzed repeatedly on 15m timeframe with 1m checks

### Root Causes
- **No validation layer** - Bad data propagated silently
- **Unclear lifecycle** - When does signal → position → trade happen?
- **Mixed concerns** - Strategies both analyzed AND decided when to exit
- **No tests** - Every fix broke something else
- **Fragile state** - Position tracking in memory dict + database, out of sync

---

## The Right Way: Test-First, Validate Everything

### Core Principles

1. **One source of truth for state** - Database is canonical, memory is cache
2. **Validate at boundaries** - API responses, user input, config files
3. **Explicit lifecycle** - Clear state machine for positions
4. **Separation of concerns** - Strategies analyze, engine decides
5. **Test before run** - Unit tests prove it works before live data
6. **Timezone-aware from start** - UTC everywhere, convert only for display
7. **Fail fast** - Crash with clear error > silent corruption

---

## Phase 1: Foundation (Test-First)

### 1.1 Data Models with Validation

**File: `src/models/candle.py`**
```python
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

@dataclass(frozen=True)  # Immutable!
class Candle:
    """OHLCV candle with validation."""
    pair: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        # Validate
        if not self.timestamp.tzinfo:
            raise ValueError("Timestamp must be timezone-aware")
        if self.high < self.low:
            raise ValueError(f"High {self.high} < Low {self.low}")
        if self.low > min(self.open, self.close):
            raise ValueError("Low must be <= open/close")
        # ... more validation

    @classmethod
    def from_alpaca(cls, bar, pair: str):
        """Convert Alpaca Bar to Candle."""
        return cls(
            pair=pair,
            timestamp=bar.timestamp,  # Already timezone-aware
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=Decimal(str(bar.volume))
        )
```

**Test: `tests/test_candle.py`**
```python
def test_candle_requires_timezone():
    with pytest.raises(ValueError, match="timezone-aware"):
        Candle(
            pair="BTC/USD",
            timestamp=datetime.now(),  # Naive!
            # ...
        )

def test_candle_validates_high_low():
    with pytest.raises(ValueError, match="High.*Low"):
        Candle(
            pair="BTC/USD",
            timestamp=datetime.now(timezone.utc),
            open=Decimal("100"),
            high=Decimal("90"),  # Invalid!
            low=Decimal("95"),
            # ...
        )
```

### 1.2 Position State Machine

**File: `src/models/position.py`**
```python
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

class PositionStatus(Enum):
    OPEN = "open"
    CLOSED = "closed"

class Direction(Enum):
    LONG = "long"
    SHORT = "short"

@dataclass
class Position:
    """Position with clear lifecycle."""
    id: str
    pair: str
    direction: Direction
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime  # NOT from signal, from actual open time!
    strategy_name: str
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Decimal | None = None
    exit_time: datetime | None = None
    exit_reason: str = ""

    def __post_init__(self):
        if not self.entry_time.tzinfo:
            raise ValueError("entry_time must be timezone-aware")
        if self.status == PositionStatus.CLOSED:
            if not self.exit_time or not self.exit_price:
                raise ValueError("Closed position must have exit_time and exit_price")

    def close(self, exit_price: Decimal, reason: str) -> "Position":
        """Return new Position object with closed status."""
        if self.status == PositionStatus.CLOSED:
            raise ValueError("Position already closed")

        return Position(
            id=self.id,
            pair=self.pair,
            direction=self.direction,
            entry_price=self.entry_price,
            quantity=self.quantity,
            entry_time=self.entry_time,
            strategy_name=self.strategy_name,
            status=PositionStatus.CLOSED,
            exit_price=exit_price,
            exit_time=datetime.now(timezone.utc),
            exit_reason=reason
        )

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L."""
        if self.status == PositionStatus.CLOSED:
            raise ValueError("Position is closed")

        if self.direction == Direction.LONG:
            return (current_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - current_price) * self.quantity

    def realized_pnl(self) -> Decimal:
        """Calculate realized P&L."""
        if self.status != PositionStatus.CLOSED:
            raise ValueError("Position not closed yet")

        if self.direction == Direction.LONG:
            return (self.exit_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - self.exit_price) * self.quantity
```

**Why this is better:**
- Immutable where possible
- Clear state transitions
- Validation built-in
- Returns new objects (functional style)
- No confusion about when times are set

### 1.3 Signal Model (Simplified)

**File: `src/models/signal.py`**
```python
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

class SignalType(Enum):
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    # Note: NO "exit" signals! Strategies don't decide exits.

@dataclass(frozen=True)
class Signal:
    """Trading signal from strategy."""
    pair: str
    signal_type: SignalType
    strength: Decimal  # 0.0 to 1.0
    strategy_name: str
    reasoning: str
    timestamp: datetime  # From candle, for reference only
    indicators: dict  # RSI, EMA values, etc.

    def __post_init__(self):
        if not (Decimal("0") <= self.strength <= Decimal("1")):
            raise ValueError("Signal strength must be 0-1")
        if not self.timestamp.tzinfo:
            raise ValueError("Timestamp must be timezone-aware")
```

**Key change:** Strategies only say "I see a LONG opportunity" or "I see a SHORT opportunity". They DON'T say "exit now". The engine decides when to close based on risk rules.

### 1.4 Database Schema (Simple & Clear)

**File: `src/data/schema.sql`**
```sql
-- Positions table (source of truth)
CREATE TABLE IF NOT EXISTS positions (
    id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,  -- 'long' or 'short'
    entry_price TEXT NOT NULL,  -- Store as string to preserve precision
    quantity TEXT NOT NULL,
    entry_time TEXT NOT NULL,  -- ISO format with timezone
    strategy_name TEXT NOT NULL,
    status TEXT NOT NULL,  -- 'open' or 'closed'
    exit_price TEXT,
    exit_time TEXT,
    exit_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_pair ON positions(pair);

-- Trades table (closed positions, for analysis)
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    pair TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry_price TEXT NOT NULL,
    exit_price TEXT NOT NULL,
    quantity TEXT NOT NULL,
    entry_time TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    pnl TEXT NOT NULL,
    pnl_pct TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    exit_reason TEXT,
    commission TEXT NOT NULL DEFAULT '0',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- Candles cache (for backtesting)
CREATE TABLE IF NOT EXISTS candles (
    pair TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open TEXT NOT NULL,
    high TEXT NOT NULL,
    low TEXT NOT NULL,
    close TEXT NOT NULL,
    volume TEXT NOT NULL,
    PRIMARY KEY (pair, timestamp)
);

-- Account state (single row)
CREATE TABLE IF NOT EXISTS account_state (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Only one row!
    balance TEXT NOT NULL,
    starting_balance TEXT NOT NULL,
    last_reset_date TEXT NOT NULL
);
```

**Why TEXT for numbers?** Decimal precision. We parse to Decimal in Python, never float.

---

## Phase 2: Core Engine (With Tests)

### 2.1 Position Manager

**File: `src/engine/position_manager.py`**
```python
class PositionManager:
    """Manages position lifecycle. Single source of truth."""

    def __init__(self, db: Database):
        self.db = db
        self._cache: dict[str, Position] = {}  # pair -> Position
        self._load_open_positions()

    def _load_open_positions(self):
        """Load open positions from database into cache."""
        positions = self.db.get_open_positions()
        self._cache = {p.pair: p for p in positions}

    def get_position(self, pair: str) -> Position | None:
        """Get open position for pair, or None."""
        return self._cache.get(pair)

    def has_position(self, pair: str) -> bool:
        """Check if pair has open position."""
        return pair in self._cache

    def open_position(self, position: Position) -> None:
        """Open new position. Raises if pair already has position."""
        if self.has_position(position.pair):
            raise ValueError(f"Already have open position for {position.pair}")

        if position.status != PositionStatus.OPEN:
            raise ValueError("Can only open positions with OPEN status")

        # Database first (source of truth)
        self.db.insert_position(position)

        # Then cache
        self._cache[position.pair] = position

    def close_position(self, pair: str, exit_price: Decimal, reason: str) -> Position:
        """Close position. Returns closed position."""
        position = self.get_position(pair)
        if not position:
            raise ValueError(f"No open position for {pair}")

        # Create closed position
        closed = position.close(exit_price, reason)

        # Database first
        self.db.update_position(closed)
        self.db.insert_trade(Trade.from_position(closed))

        # Then cache
        del self._cache[pair]

        return closed

    def get_all_open(self) -> list[Position]:
        """Get all open positions."""
        return list(self._cache.values())
```

**Test: `tests/test_position_manager.py`**
```python
def test_cannot_open_duplicate_position():
    db = InMemoryDatabase()  # Mock
    pm = PositionManager(db)

    pos1 = Position(
        id="1",
        pair="BTC/USD",
        direction=Direction.LONG,
        # ...
    )

    pm.open_position(pos1)

    pos2 = Position(id="2", pair="BTC/USD", ...)

    with pytest.raises(ValueError, match="Already have open position"):
        pm.open_position(pos2)

def test_close_updates_database_and_cache():
    db = InMemoryDatabase()
    pm = PositionManager(db)

    pos = Position(...)
    pm.open_position(pos)

    closed = pm.close_position("BTC/USD", Decimal("50000"), "Test exit")

    assert closed.status == PositionStatus.CLOSED
    assert pm.get_position("BTC/USD") is None  # Removed from cache
    assert db.get_trade(pos.id) is not None  # Added to trades table
```

### 2.2 Risk Manager (Pure Functions)

**File: `src/engine/risk_manager.py`**
```python
from dataclasses import dataclass
from decimal import Decimal

@dataclass
class RiskLimits:
    """Risk management configuration."""
    max_position_pct: Decimal  # 0.1 = 10%
    max_open_positions: int
    max_daily_loss_pct: Decimal
    stop_loss_pct: Decimal  # Per-position
    take_profit_pct: Decimal
    min_signal_strength: Decimal  # 0.7 = 70%

class RiskManager:
    """Pure functions for risk checks. No state."""

    def __init__(self, limits: RiskLimits):
        self.limits = limits

    def can_open_position(
        self,
        signal: Signal,
        current_positions: list[Position],
        account_value: Decimal,
        starting_balance: Decimal
    ) -> tuple[bool, str]:
        """Check if signal passes risk checks."""

        # Check 1: Already have position for this pair?
        if any(p.pair == signal.pair for p in current_positions):
            return False, f"Already have position for {signal.pair}"

        # Check 2: Too many positions?
        if len(current_positions) >= self.limits.max_open_positions:
            return False, f"Max positions ({self.limits.max_open_positions}) reached"

        # Check 3: Daily loss limit?
        daily_pnl_pct = (account_value - starting_balance) / starting_balance
        if daily_pnl_pct <= -self.limits.max_daily_loss_pct:
            return False, f"Daily loss limit hit: {daily_pnl_pct:.2%}"

        # Check 4: Signal too weak?
        if signal.strength < self.limits.min_signal_strength:
            return False, f"Signal strength {signal.strength:.2f} < minimum {self.limits.min_signal_strength:.2f}"

        return True, "Risk checks passed"

    def calculate_position_size(
        self,
        account_value: Decimal,
        current_price: Decimal
    ) -> Decimal:
        """Calculate position size based on account value."""
        max_value = account_value * self.limits.max_position_pct
        quantity = max_value / current_price
        return quantity

    def should_close_position(
        self,
        position: Position,
        current_price: Decimal
    ) -> tuple[bool, str]:
        """Check if position should be closed (stop loss / take profit)."""
        pnl = position.unrealized_pnl(current_price)
        pnl_pct = pnl / (position.entry_price * position.quantity)

        # Stop loss
        if pnl_pct <= -self.limits.stop_loss_pct:
            return True, f"Stop loss hit: {pnl_pct:.2%}"

        # Take profit
        if pnl_pct >= self.limits.take_profit_pct:
            return True, f"Take profit hit: {pnl_pct:.2%}"

        return False, ""
```

**Test: `tests/test_risk_manager.py`**
```python
def test_blocks_duplicate_pair():
    limits = RiskLimits(
        max_position_pct=Decimal("0.1"),
        max_open_positions=3,
        # ...
    )
    rm = RiskManager(limits)

    signal = Signal(pair="BTC/USD", ...)
    positions = [Position(pair="BTC/USD", ...)]

    allowed, reason = rm.can_open_position(
        signal, positions, Decimal("10000"), Decimal("10000")
    )

    assert not allowed
    assert "Already have position" in reason

def test_enforces_max_positions():
    limits = RiskLimits(max_open_positions=2, ...)
    rm = RiskManager(limits)

    signal = Signal(pair="ETH/USD", ...)
    positions = [
        Position(pair="BTC/USD", ...),
        Position(pair="SOL/USD", ...)
    ]

    allowed, reason = rm.can_open_position(signal, positions, ...)

    assert not allowed
    assert "Max positions (2) reached" in reason
```

### 2.3 Paper Trader

**File: `src/engine/paper_trader.py`**
```python
class PaperTrader:
    """Executes trades in simulation."""

    def __init__(
        self,
        position_manager: PositionManager,
        risk_manager: RiskManager,
        starting_balance: Decimal
    ):
        self.pm = position_manager
        self.rm = risk_manager
        self.balance = starting_balance
        self.starting_balance = starting_balance

        # Load balance from database if exists
        saved = self.pm.db.get_account_state()
        if saved:
            self.balance = saved.balance
            self.starting_balance = saved.starting_balance

    def execute_signal(
        self,
        signal: Signal,
        current_price: Decimal
    ) -> Position | None:
        """
        Try to execute signal. Returns Position if opened, None if rejected.
        """
        # Risk check
        allowed, reason = self.rm.can_open_position(
            signal,
            self.pm.get_all_open(),
            self.get_portfolio_value({signal.pair: current_price}),
            self.starting_balance
        )

        if not allowed:
            logger.info(f"Signal rejected: {reason}")
            return None

        # Calculate position size
        quantity = self.rm.calculate_position_size(
            self.get_portfolio_value({signal.pair: current_price}),
            current_price
        )

        # Apply slippage
        slippage = Decimal("0.001")  # 0.1%
        if signal.signal_type == SignalType.ENTRY_LONG:
            entry_price = current_price * (1 + slippage)
        else:  # SHORT
            entry_price = current_price * (1 - slippage)

        # Calculate cost
        position_value = quantity * entry_price
        commission = position_value * Decimal("0.001")  # 0.1%
        total_cost = position_value + commission

        # Check balance
        if total_cost > self.balance:
            logger.warning(f"Insufficient balance: need {total_cost}, have {self.balance}")
            return None

        # Create position
        position = Position(
            id=str(uuid.uuid4()),
            pair=signal.pair,
            direction=Direction.LONG if signal.signal_type == SignalType.ENTRY_LONG else Direction.SHORT,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(timezone.utc),  # ACTUAL trade time!
            strategy_name=signal.strategy_name,
            status=PositionStatus.OPEN
        )

        # Deduct balance
        self.balance -= total_cost

        # Open position (database + cache)
        self.pm.open_position(position)

        # Save state
        self._save_state()

        return position

    def close_position(
        self,
        pair: str,
        current_price: Decimal,
        reason: str
    ) -> Position | None:
        """Close position for pair."""
        if not self.pm.has_position(pair):
            return None

        position = self.pm.get_position(pair)

        # Apply slippage
        slippage = Decimal("0.001")
        if position.direction == Direction.LONG:
            exit_price = current_price * (1 - slippage)
        else:  # SHORT
            exit_price = current_price * (1 + slippage)

        # Close position
        closed = self.pm.close_position(pair, exit_price, reason)

        # Calculate proceeds
        pnl = closed.realized_pnl()
        position_value = closed.quantity * closed.entry_price
        exit_value = closed.quantity * exit_price
        commission = exit_value * Decimal("0.001")

        proceeds = position_value + pnl - commission

        # Add to balance
        self.balance += proceeds

        # Save state
        self._save_state()

        return closed

    def get_portfolio_value(self, current_prices: dict[str, Decimal]) -> Decimal:
        """Calculate total portfolio value."""
        value = self.balance

        for position in self.pm.get_all_open():
            if position.pair in current_prices:
                unrealized = position.unrealized_pnl(current_prices[position.pair])
                position_value = position.quantity * position.entry_price
                value += position_value + unrealized

        return value
```

---

## Phase 3: Strategy Framework

### 3.1 Base Strategy (Clean Interface)

**File: `src/strategies/base.py`**
```python
from abc import ABC, abstractmethod

class Strategy(ABC):
    """Base strategy that only analyzes, doesn't decide when to exit."""

    name: str
    description: str
    min_candles_required: int

    @abstractmethod
    def configure(self, params: dict) -> None:
        """Load configuration."""
        pass

    @abstractmethod
    def analyze(self, candles: list[Candle]) -> Signal | None:
        """
        Analyze candles and return ENTRY signal if conditions met.

        Returns:
            Signal for ENTRY_LONG or ENTRY_SHORT, or None

        Note: Strategies do NOT generate exit signals!
        The engine handles exits based on risk rules.
        """
        pass

    @abstractmethod
    def get_default_params(self) -> dict:
        """Return default parameters."""
        pass
```

**Key change:** Strategies only look for entry opportunities. No more "NEUTRAL" exit signals that conflict with other strategies!

### 3.2 Example Strategy

**File: `src/strategies/ema_rsi.py`**
```python
class EmaRsiStrategy(Strategy):
    """EMA + RSI mean reversion ENTRY signals only."""

    name = "ema_rsi"
    description = "EMA + RSI mean reversion strategy"
    min_candles_required = 100

    def configure(self, params: dict):
        self.ema_period = params.get("ema_period", 100)
        self.rsi_period = params.get("rsi_period", 14)
        self.rsi_oversold = params.get("rsi_oversold", 30)
        self.rsi_overbought = params.get("rsi_overbought", 70)

    def analyze(self, candles: list[Candle]) -> Signal | None:
        """Look for entry opportunities only."""
        if len(candles) < self.min_candles_required:
            return None

        # Calculate indicators
        closes = [c.close for c in candles]
        ema = self._calculate_ema(closes, self.ema_period)
        rsi = self._calculate_rsi(closes, self.rsi_period)

        current_price = candles[-1].close
        current_rsi = rsi[-1]
        prev_rsi = rsi[-2]
        current_ema = ema[-1]

        # LONG: RSI crosses above oversold while price < EMA
        if (
            prev_rsi <= self.rsi_oversold
            and current_rsi > self.rsi_oversold
            and current_price < current_ema
        ):
            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=Decimal("0.75"),
                strategy_name=self.name,
                reasoning=f"RSI crossed above oversold ({prev_rsi:.1f} -> {current_rsi:.1f}) while price {current_price} < EMA {current_ema}",
                timestamp=candles[-1].timestamp,
                indicators={"rsi": float(current_rsi), "ema": float(current_ema), "price": float(current_price)}
            )

        # SHORT: RSI crosses below overbought while price > EMA
        if (
            prev_rsi >= self.rsi_overbought
            and current_rsi < self.rsi_overbought
            and current_price > current_ema
        ):
            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=Decimal("0.75"),
                strategy_name=self.name,
                reasoning=f"RSI crossed below overbought ({prev_rsi:.1f} -> {current_rsi:.1f}) while price {current_price} > EMA {current_ema}",
                timestamp=candles[-1].timestamp,
                indicators={"rsi": float(current_rsi), "ema": float(current_ema), "price": float(current_price)}
            )

        # No entry signal
        return None
```

**Exits are handled by the engine:**
- Stop loss at -2%
- Take profit at +5%
- Or time-based exit after X hours

---

## Phase 4: Main Loop (Clear & Simple)

**File: `src/main.py`**
```python
class TradingBot:
    """Main orchestrator."""

    async def run(self):
        """Main trading loop - simple and clear."""
        while self.running:
            try:
                # 1. Fetch current prices
                prices = await self._fetch_prices()

                # 2. Check existing positions for exits (risk-based)
                await self._check_position_exits(prices)

                # 3. Look for new entry opportunities
                await self._check_entry_signals(prices)

                # 4. Log status periodically
                if self.iteration % 10 == 0:
                    self._log_portfolio_status(prices)

                # 5. Sleep
                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Loop error: {e}", exc_info=True)
                await asyncio.sleep(5)

    async def _check_position_exits(self, prices: dict[str, Decimal]):
        """Check if any open positions should close."""
        for position in self.paper_trader.pm.get_all_open():
            if position.pair not in prices:
                continue

            current_price = prices[position.pair]

            # Risk-based exit check
            should_close, reason = self.risk_manager.should_close_position(
                position, current_price
            )

            if should_close:
                closed = self.paper_trader.close_position(
                    position.pair, current_price, reason
                )
                logger.info(f"Position closed: {closed.pair} | {reason} | P&L: {closed.realized_pnl()}")

    async def _check_entry_signals(self, prices: dict[str, Decimal]):
        """Check all pairs for entry signals."""
        for pair in self.pairs:
            # Skip if already have position
            if self.paper_trader.pm.has_position(pair):
                continue

            if pair not in prices:
                continue

            # Fetch candles
            candles = await self.fetcher.fetch_candles(pair, self.timeframe, 200)
            if not candles:
                continue

            # Run strategies (only first signal wins)
            for strategy in self.strategies:
                signal = strategy.analyze(candles)

                if signal:
                    logger.info(f"Signal: {signal.signal_type.value} {pair} | {signal.reasoning}")

                    # Try to execute
                    position = self.paper_trader.execute_signal(signal, prices[pair])

                    if position:
                        logger.info(f"Position opened: {position.pair} | {position.direction.value} | Qty: {position.quantity}")
                        break  # Only one strategy per pair per iteration
```

**Why this is better:**
- Each step is obvious
- No complex nested logic
- Clear separation: exits first, then entries
- Only one position per pair
- Strategies can't conflict

---

## Phase 5: Testing Strategy

### Test Pyramid

```
         E2E Tests (Few)
       ↗                ↘
   Integration Tests (Some)
  ↗                        ↘
Unit Tests (Many - Fast!)
```

### Unit Tests (Run in < 1 second)
```bash
pytest tests/test_models.py        # Data validation
pytest tests/test_risk_manager.py  # Risk logic
pytest tests/test_strategies.py    # Strategy calculations
```

### Integration Tests (Database, slower)
```bash
pytest tests/test_position_manager.py  # DB operations
pytest tests/test_paper_trader.py      # Full trade lifecycle
```

### E2E Test (Mock Alpaca)
```bash
pytest tests/test_bot.py  # Full bot with mock connector
```

---

## Build Order (Test-First)

### Day 1: Foundation (2-3 hours)
1. ✅ Data models with tests
2. ✅ Database layer with tests
3. ✅ Position manager with tests
4. ✅ Risk manager with tests

### Day 2: Execution (2-3 hours)
5. ✅ Paper trader with tests
6. ✅ Alpaca connector (reuse/fix existing)
7. ✅ Integration tests

### Day 3: Strategies (1-2 hours)
8. ✅ Base strategy framework
9. ✅ Port existing strategies (EMA+RSI, EMA Crossover)
10. ✅ Strategy tests

### Day 4: Integration (1-2 hours)
11. ✅ Main loop
12. ✅ Config loading
13. ✅ Logging
14. ✅ E2E test

### Day 5: Polish (1 hour)
15. ✅ Run on real data for 1 hour
16. ✅ Fix any issues found
17. ✅ Documentation

---

## Success Metrics

**Before going live (even paper trading):**
- [ ] All unit tests pass
- [ ] All integration tests pass
- [ ] E2E test with mock data runs for 100 iterations without errors
- [ ] Manual review of test logs shows correct behavior
- [ ] No duplicate positions in any test scenario
- [ ] All datetime operations use timezone-aware datetimes
- [ ] All numeric operations use Decimal, not float
- [ ] Database and memory state stay in sync

**Only then:** Run with real Alpaca data for supervised testing.

---

## Key Differences from v1

| Aspect | v1 (Broken) | v2 (Robust) |
|--------|-------------|-------------|
| **State** | Dict + DB, out of sync | DB is source of truth |
| **Validation** | None | Every boundary |
| **Timestamps** | Mixed naive/aware | UTC everywhere |
| **Numbers** | float (precision loss) | Decimal (exact) |
| **Strategy role** | Analyze + exit | Analyze only |
| **Exit logic** | Per strategy | Centralized in engine |
| **Testing** | None | Test-first |
| **Error handling** | Silent failures | Fail fast, loud |
| **Lifecycle** | Unclear | Explicit state machine |

---

## What We Keep from v1

The good parts that worked:
- Alpaca connector structure (with fixes)
- Strategy calculation logic (EMA, RSI, etc)
- Config YAML approach
- Logging framework
- Overall project structure

---

## Final Thought

**v1 taught us what NOT to do.**
**v2 will be built on those lessons.**

The foundation will be solid. The tests will give us confidence. The architecture will be clear.

And when we hit the "run" button, we'll know it works because we already tested it 100 times.

Let's build it right. 🔥
