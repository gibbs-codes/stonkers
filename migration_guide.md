# Algo Trading Bot - Alpaca Migration Guide

## Context

You have an existing algo trading bot built for Binance that needs to work with Alpaca instead. Binance is not available to US customers, but Alpaca offers:
- Full paper trading with real market data
- US availability (most states)
- Excellent Python SDK
- Commission-free trading

**This is a migration, not a rewrite.** Most of your code should remain intact.

---

## What Changes vs What Stays

### ✅ Keep These (No Changes Needed)
- `src/strategies/` - All strategy implementations
- `src/engine/paper_trader.py` - Paper trading logic
- `src/engine/risk_manager.py` - Risk management
- `src/logging/trade_logger.py` - Logging infrastructure
- `src/data/models.py` - Data classes (Candle, Signal, Trade, Position)
- `configs/` - Strategy parameter configs (mostly)
- Project structure

### 🔄 Modify These
- `src/config/settings.py` - Add Alpaca credential handling
- `src/config/default_config.yaml` - Update exchange config section
- `src/data/fetcher.py` - Update to use Alpaca data API
- `src/main.py` - Update initialization if needed

### ➕ Add These
- `src/connectors/alpaca.py` - New Alpaca connector
- Keep `src/connectors/binance.py` if you want (for reference or future use)

### 🗑️ Can Remove (Optional)
- Binance-specific code paths
- Binance testnet configuration

---

## Step-by-Step Migration

### Step 1: Install Alpaca Dependencies

Update `requirements.txt`:
```
# Remove or comment out binance-specific packages if any

# Add Alpaca packages
alpaca-py>=0.13.0

# ccxt still works but alpaca-py is more feature-complete for Alpaca
# ccxt>=4.0.0  # Optional - can use for Alpaca too
```

Run:
```bash
pip install alpaca-py --break-system-packages
```

### Step 2: Update Configuration

Update `src/config/default_config.yaml`:

```yaml
exchange:
  name: alpaca
  paper_trading: true  # ALWAYS true until explicitly changed
  
  # Alpaca-specific settings
  alpaca:
    # Credentials loaded from environment variables
    # ALPACA_API_KEY and ALPACA_SECRET_KEY
    data_feed: "iex"  # "iex" (free) or "sip" (paid, more accurate)

trading:
  pairs:
    - BTC/USD      # Note: Alpaca uses USD, not USDT
    - ETH/USD
    - DOGE/USD
  default_timeframe: 15m  # Alpaca supports: 1m, 5m, 15m, 1h, 1d
  
paper_trading:
  enabled: true
  starting_balance: 10000  # USD
  
risk:
  max_position_pct: 0.1
  max_daily_loss_pct: 0.05
  max_open_positions: 3
  default_leverage: 1  # Alpaca crypto is spot-only, no leverage

logging:
  level: INFO
  log_signals: true
  log_decisions: true
  log_to_file: true
```

### Step 3: Set Environment Variables

Create `.env` file or export:
```bash
export ALPACA_API_KEY="your_paper_api_key"
export ALPACA_SECRET_KEY="your_paper_secret_key"
```

Get these from: https://app.alpaca.markets/paper/dashboard/overview
(Make sure you're on the Paper Trading dashboard, not live)

### Step 4: Create Alpaca Connector

Create `src/connectors/alpaca.py`:

```python
"""
Alpaca Exchange Connector

Handles all communication with Alpaca's API for both
market data and trade execution.
"""

import os
from datetime import datetime, timedelta
from typing import Optional
import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest
)
from alpaca.trading.enums import OrderSide, TimeInForce, OrderStatus
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.connectors.base import ExchangeConnector
from src.data.models import Candle, Position

logger = logging.getLogger(__name__)


class AlpacaConnector(ExchangeConnector):
    """
    Alpaca exchange connector for crypto trading.
    
    Supports both paper trading and live trading.
    Paper trading is the default and recommended for development.
    """
    
    # Timeframe mapping from string to Alpaca TimeFrame
    TIMEFRAME_MAP = {
        "1m": TimeFrame(1, TimeFrameUnit.Minute),
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "30m": TimeFrame(30, TimeFrameUnit.Minute),
        "1h": TimeFrame(1, TimeFrameUnit.Hour),
        "4h": TimeFrame(4, TimeFrameUnit.Hour),
        "1d": TimeFrame(1, TimeFrameUnit.Day),
    }
    
    def __init__(self, config: dict):
        """
        Initialize Alpaca connector.
        
        Args:
            config: Configuration dictionary with exchange settings
        """
        self.config = config
        self.paper_trading = config.get("paper_trading", True)
        
        # Get credentials from environment
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        
        if not api_key or not secret_key:
            raise ValueError(
                "ALPACA_API_KEY and ALPACA_SECRET_KEY environment variables required"
            )
        
        # Initialize trading client
        self.trading_client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=self.paper_trading
        )
        
        # Initialize data client (no auth needed for crypto data)
        self.data_client = CryptoHistoricalDataClient()
        
        logger.info(
            f"Alpaca connector initialized (paper_trading={self.paper_trading})"
        )
    
    def get_account_balance(self) -> dict:
        """
        Get current account balance.
        
        Returns:
            Dictionary with currency balances
        """
        account = self.trading_client.get_account()
        return {
            "USD": float(account.cash),
            "equity": float(account.equity),
            "buying_power": float(account.buying_power),
        }
    
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> list[Candle]:
        """
        Fetch OHLCV (candlestick) data.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe: Candle timeframe (e.g., "15m", "1h")
            limit: Number of candles to fetch
            since: Start time (optional)
            
        Returns:
            List of Candle objects
        """
        # Convert symbol format: "BTC/USD" -> "BTC/USD" (Alpaca uses same format)
        alpaca_symbol = symbol
        
        # Get timeframe
        tf = self.TIMEFRAME_MAP.get(timeframe)
        if not tf:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        # Calculate start time if not provided
        if since is None:
            # Estimate time needed for `limit` candles
            minutes_per_candle = self._timeframe_to_minutes(timeframe)
            since = datetime.utcnow() - timedelta(minutes=minutes_per_candle * limit * 1.5)
        
        # Build request
        request = CryptoBarsRequest(
            symbol_or_symbols=alpaca_symbol,
            timeframe=tf,
            start=since,
            limit=limit
        )
        
        # Fetch data
        bars = self.data_client.get_crypto_bars(request)
        
        # Convert to Candle objects
        candles = []
        if alpaca_symbol in bars:
            for bar in bars[alpaca_symbol]:
                candle = Candle(
                    timestamp=bar.timestamp,
                    open=float(bar.open),
                    high=float(bar.high),
                    low=float(bar.low),
                    close=float(bar.close),
                    volume=float(bar.volume)
                )
                candles.append(candle)
        
        logger.debug(f"Fetched {len(candles)} candles for {symbol} ({timeframe})")
        return candles
    
    def get_current_price(self, symbol: str) -> float:
        """
        Get current price for a symbol.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            
        Returns:
            Current price as float
        """
        # Fetch the most recent candle
        candles = self.fetch_ohlcv(symbol, timeframe="1m", limit=1)
        if candles:
            return candles[-1].close
        raise ValueError(f"Could not fetch price for {symbol}")
    
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> dict:
        """
        Place a market order.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            side: "buy" or "sell"
            quantity: Amount to trade
            
        Returns:
            Order details dictionary
        """
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        
        request = MarketOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.GTC
        )
        
        order = self.trading_client.submit_order(request)
        
        logger.info(
            f"Market order placed: {side} {quantity} {symbol} "
            f"(order_id={order.id})"
        )
        
        return {
            "id": str(order.id),
            "symbol": symbol,
            "side": side,
            "quantity": float(order.qty),
            "status": str(order.status),
            "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
            "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
        }
    
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> dict:
        """
        Place a limit order.
        
        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            side: "buy" or "sell"
            quantity: Amount to trade
            price: Limit price
            
        Returns:
            Order details dictionary
        """
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        
        request = LimitOrderRequest(
            symbol=symbol,
            qty=quantity,
            side=order_side,
            time_in_force=TimeInForce.GTC,
            limit_price=price
        )
        
        order = self.trading_client.submit_order(request)
        
        logger.info(
            f"Limit order placed: {side} {quantity} {symbol} @ {price} "
            f"(order_id={order.id})"
        )
        
        return {
            "id": str(order.id),
            "symbol": symbol,
            "side": side,
            "quantity": float(order.qty),
            "price": price,
            "status": str(order.status),
        }
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        try:
            self.trading_client.cancel_order_by_id(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False
    
    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """
        Get all open orders.
        
        Args:
            symbol: Optional filter by symbol
            
        Returns:
            List of order dictionaries
        """
        request = GetOrdersRequest(status="open")
        orders = self.trading_client.get_orders(request)
        
        result = []
        for order in orders:
            if symbol is None or order.symbol == symbol:
                result.append({
                    "id": str(order.id),
                    "symbol": order.symbol,
                    "side": str(order.side),
                    "quantity": float(order.qty),
                    "filled_qty": float(order.filled_qty) if order.filled_qty else 0,
                    "status": str(order.status),
                })
        
        return result
    
    def get_positions(self) -> list[Position]:
        """
        Get all open positions.
        
        Returns:
            List of Position objects
        """
        positions = self.trading_client.get_all_positions()
        
        result = []
        for pos in positions:
            position = Position(
                symbol=pos.symbol,
                side="long" if float(pos.qty) > 0 else "short",
                quantity=abs(float(pos.qty)),
                entry_price=float(pos.avg_entry_price),
                current_price=float(pos.current_price),
                unrealized_pnl=float(pos.unrealized_pl),
            )
            result.append(position)
        
        return result
    
    def _timeframe_to_minutes(self, timeframe: str) -> int:
        """Convert timeframe string to minutes."""
        mapping = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }
        return mapping.get(timeframe, 15)
```

### Step 5: Update Base Connector Interface

Ensure `src/connectors/base.py` has a clean interface:

```python
"""
Abstract base class for exchange connectors.

All exchange implementations should inherit from this class
to ensure consistent interface across different exchanges.
"""

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

from src.data.models import Candle, Position


class ExchangeConnector(ABC):
    """Abstract base class for exchange connectors."""
    
    @abstractmethod
    def get_account_balance(self) -> dict:
        """Get current account balance."""
        pass
    
    @abstractmethod
    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 100,
        since: Optional[datetime] = None
    ) -> list[Candle]:
        """Fetch OHLCV candlestick data."""
        pass
    
    @abstractmethod
    def get_current_price(self, symbol: str) -> float:
        """Get current price for a symbol."""
        pass
    
    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float
    ) -> dict:
        """Place a market order."""
        pass
    
    @abstractmethod
    def place_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float
    ) -> dict:
        """Place a limit order."""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        pass
    
    @abstractmethod
    def get_open_orders(self, symbol: Optional[str] = None) -> list[dict]:
        """Get all open orders."""
        pass
    
    @abstractmethod
    def get_positions(self) -> list[Position]:
        """Get all open positions."""
        pass
```

### Step 6: Update Data Fetcher

Update `src/data/fetcher.py` to use the connector abstraction:

```python
"""
Data fetcher that works with any exchange connector.
"""

from datetime import datetime, timedelta
from typing import Optional
import logging

from src.connectors.base import ExchangeConnector
from src.data.models import Candle
from src.data.storage import DataStorage

logger = logging.getLogger(__name__)


class DataFetcher:
    """
    Fetches and manages market data from exchanges.
    
    Works with any ExchangeConnector implementation.
    """
    
    def __init__(
        self,
        connector: ExchangeConnector,
        storage: Optional[DataStorage] = None
    ):
        """
        Initialize data fetcher.
        
        Args:
            connector: Exchange connector instance
            storage: Optional storage for caching data
        """
        self.connector = connector
        self.storage = storage
    
    def get_candles(
        self,
        symbol: str,
        timeframe: str = "15m",
        limit: int = 100,
        use_cache: bool = True
    ) -> list[Candle]:
        """
        Get candles, using cache if available.
        
        Args:
            symbol: Trading pair
            timeframe: Candle timeframe
            limit: Number of candles
            use_cache: Whether to use cached data
            
        Returns:
            List of Candle objects
        """
        # Try cache first
        if use_cache and self.storage:
            cached = self.storage.get_candles(symbol, timeframe, limit)
            if cached and len(cached) >= limit:
                logger.debug(f"Using cached data for {symbol}")
                return cached[-limit:]
        
        # Fetch from exchange
        candles = self.connector.fetch_ohlcv(
            symbol=symbol,
            timeframe=timeframe,
            limit=limit
        )
        
        # Store in cache
        if self.storage and candles:
            self.storage.save_candles(symbol, timeframe, candles)
        
        return candles
    
    def get_latest_candle(self, symbol: str, timeframe: str = "15m") -> Optional[Candle]:
        """Get the most recent candle."""
        candles = self.get_candles(symbol, timeframe, limit=1, use_cache=False)
        return candles[-1] if candles else None
    
    def get_current_price(self, symbol: str) -> float:
        """Get current price."""
        return self.connector.get_current_price(symbol)
```

### Step 7: Create Connector Factory

Add `src/connectors/__init__.py`:

```python
"""
Connector factory for creating exchange connectors.
"""

from src.connectors.base import ExchangeConnector
from src.connectors.alpaca import AlpacaConnector


def create_connector(config: dict) -> ExchangeConnector:
    """
    Create an exchange connector based on configuration.
    
    Args:
        config: Configuration dictionary with 'exchange' section
        
    Returns:
        ExchangeConnector instance
    """
    exchange_name = config.get("exchange", {}).get("name", "alpaca").lower()
    
    if exchange_name == "alpaca":
        return AlpacaConnector(config.get("exchange", {}))
    # Add other exchanges here as needed:
    # elif exchange_name == "kraken":
    #     return KrakenConnector(config.get("exchange", {}))
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")
```

### Step 8: Update Main Entry Point

Update `src/main.py` to use the factory:

```python
"""
Main entry point for the algo trading bot.
"""

import asyncio
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from src.config.settings import load_config
from src.connectors import create_connector
from src.data.fetcher import DataFetcher
from src.data.storage import DataStorage
from src.engine.paper_trader import PaperTrader
from src.engine.risk_manager import RiskManager
from src.strategies import load_strategies
from src.logging.trade_logger import setup_logging

# Load environment variables
load_dotenv()


def main():
    """Main entry point."""
    # Setup logging
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Load configuration
    config = load_config()
    logger.info("Configuration loaded")
    
    # Create exchange connector
    connector = create_connector(config)
    logger.info(f"Connected to {config['exchange']['name']}")
    
    # Verify connection
    balance = connector.get_account_balance()
    logger.info(f"Account balance: ${balance.get('USD', 0):.2f}")
    
    # Initialize components
    storage = DataStorage(Path("data/market_data.db"))
    fetcher = DataFetcher(connector, storage)
    risk_manager = RiskManager(config.get("risk", {}))
    paper_trader = PaperTrader(
        connector=connector,
        risk_manager=risk_manager,
        config=config.get("paper_trading", {})
    )
    
    # Load strategies
    strategies = load_strategies(config.get("strategies", {}))
    logger.info(f"Loaded {len(strategies)} strategies")
    
    # Run main loop
    try:
        asyncio.run(trading_loop(
            fetcher=fetcher,
            paper_trader=paper_trader,
            strategies=strategies,
            config=config
        ))
    except KeyboardInterrupt:
        logger.info("Shutting down...")


async def trading_loop(fetcher, paper_trader, strategies, config):
    """Main trading loop."""
    logger = logging.getLogger(__name__)
    pairs = config.get("trading", {}).get("pairs", ["BTC/USD"])
    timeframe = config.get("trading", {}).get("default_timeframe", "15m")
    
    logger.info(f"Starting trading loop for {pairs} on {timeframe}")
    
    while True:
        for pair in pairs:
            try:
                # Fetch latest candles
                candles = fetcher.get_candles(pair, timeframe, limit=200)
                
                if not candles:
                    logger.warning(f"No candles received for {pair}")
                    continue
                
                # Run each strategy
                for strategy in strategies:
                    if len(candles) < strategy.required_history:
                        continue
                    
                    signal = strategy.analyze(candles)
                    
                    if signal:
                        # Process signal through paper trader
                        paper_trader.process_signal(signal)
                
            except Exception as e:
                logger.error(f"Error processing {pair}: {e}", exc_info=True)
        
        # Wait for next candle
        # For 15m timeframe, check every minute for responsiveness
        await asyncio.sleep(60)


if __name__ == "__main__":
    main()
```

---

## Symbol Format Differences

| Exchange | Format | Example |
|----------|--------|---------|
| Binance | BASE/QUOTE | BTC/USDT |
| Alpaca | BASE/USD | BTC/USD |

**Note:** Alpaca only supports USD pairs for crypto, not USDT or other stablecoins.

Update your trading pairs in config:
```yaml
# Before (Binance)
pairs:
  - BTC/USDT
  - ETH/USDT

# After (Alpaca)
pairs:
  - BTC/USD
  - ETH/USD
```

---

## Available Crypto on Alpaca

As of 2024, Alpaca supports ~20 crypto assets including:
- BTC, ETH, DOGE, SHIB, AVAX, SOL, MATIC, LINK, UNI, AAVE, LTC, BCH, and more

Check current list: https://docs.alpaca.markets/docs/crypto-trading

---

## Testing the Migration

### Quick Smoke Test

```python
# test_alpaca_connection.py
import os
from alpaca.trading.client import TradingClient
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from datetime import datetime, timedelta

# Paper trading credentials
api_key = os.getenv("ALPACA_API_KEY")
secret_key = os.getenv("ALPACA_SECRET_KEY")

# Test trading client
trading = TradingClient(api_key, secret_key, paper=True)
account = trading.get_account()
print(f"Account status: {account.status}")
print(f"Cash: ${float(account.cash):.2f}")
print(f"Buying power: ${float(account.buying_power):.2f}")

# Test data client
data = CryptoHistoricalDataClient()
request = CryptoBarsRequest(
    symbol_or_symbols="BTC/USD",
    timeframe=TimeFrame(15, TimeFrameUnit.Minute),
    start=datetime.utcnow() - timedelta(hours=24),
    limit=10
)
bars = data.get_crypto_bars(request)
print(f"\nLast 10 BTC/USD 15m candles:")
for bar in bars["BTC/USD"]:
    print(f"  {bar.timestamp}: O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f}")
```

Run:
```bash
python test_alpaca_connection.py
```

Expected output:
```
Account status: ACTIVE
Cash: $100000.00
Buying power: $100000.00

Last 10 BTC/USD 15m candles:
  2024-01-15 10:00:00: O=42150.00 H=42200.00 L=42100.00 C=42180.00
  ...
```

---

## Summary: Migration Checklist

- [ ] Install `alpaca-py` package
- [ ] Create Alpaca paper trading account at alpaca.markets
- [ ] Get API keys from paper trading dashboard
- [ ] Set environment variables (ALPACA_API_KEY, ALPACA_SECRET_KEY)
- [ ] Create `src/connectors/alpaca.py`
- [ ] Update `src/connectors/base.py` interface
- [ ] Create connector factory in `src/connectors/__init__.py`
- [ ] Update config YAML (exchange name, symbol format)
- [ ] Update data fetcher to use connector abstraction
- [ ] Update main.py to use factory pattern
- [ ] Run smoke test to verify connection
- [ ] Test with one strategy on paper trading

---

## Troubleshooting

### "Invalid API Key"
- Make sure you're using paper trading keys, not live keys
- Verify environment variables are set correctly
- Check that you're connecting to paper endpoint (paper=True)

### "Symbol not found"
- Alpaca uses `BTC/USD` format, not `BTCUSD` or `BTC/USDT`
- Check the symbol is in Alpaca's supported list

### "No data returned"
- Crypto data doesn't require authentication
- Check your date range isn't in the future
- Verify the symbol format

### Rate Limits
- Alpaca has generous limits: 200 requests/minute for trading, unlimited for data
- Implement exponential backoff if you hit limits