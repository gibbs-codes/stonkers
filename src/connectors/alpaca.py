"""Alpaca Exchange Connector.

Handles all communication with Alpaca's API for both
market data and trade execution.
"""
import os
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
import logging

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest, GetOrdersRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.connectors.base import ExchangeConnector
from src.data.models import Candle

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

    def __init__(self, paper_trading: bool = True):
        """
        Initialize Alpaca connector.

        Args:
            paper_trading: Whether to use paper trading (default: True)
        """
        self.paper_trading = paper_trading

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

    async def connect(self) -> bool:
        """
        Test connection to Alpaca.

        Returns:
            True if connection successful
        """
        try:
            account = self.trading_client.get_account()
            logger.info(f"Connected to Alpaca. Account status: {account.status}")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Alpaca: {e}")
            return False

    async def get_balance(self, currency: str = 'USD') -> float:
        """
        Get account balance.

        Args:
            currency: Currency symbol (default: USD)

        Returns:
            Available balance
        """
        try:
            account = self.trading_client.get_account()
            if currency == 'USD':
                return float(account.cash)
            return 0.0
        except Exception as e:
            logger.error(f"Error fetching balance: {e}")
            return 0.0

    async def fetch_ohlcv(
        self,
        pair: str,
        timeframe: str,
        since: datetime = None,
        limit: int = 100
    ) -> List[Candle]:
        """
        Fetch OHLCV (candlestick) data.

        Args:
            pair: Trading pair (e.g., "BTC/USD" or "BTCUSD")
            timeframe: Candle timeframe (e.g., "15m", "1h")
            since: Start time (optional)
            limit: Number of candles to fetch

        Returns:
            List of Candle objects
        """
        try:
            # Alpaca uses "BTC/USD" format with slash for crypto
            # No conversion needed - use pair as-is

            # Get timeframe
            tf = self.TIMEFRAME_MAP.get(timeframe)
            if not tf:
                raise ValueError(f"Unsupported timeframe: {timeframe}")

            # Calculate start time if not provided
            if since is None:
                minutes_per_candle = self._timeframe_to_minutes(timeframe)
                since = datetime.now(timezone.utc) - timedelta(minutes=minutes_per_candle * limit * 1.5)

            # Build request
            request = CryptoBarsRequest(
                symbol_or_symbols=pair,
                timeframe=tf,
                start=since,
                limit=limit
            )

            # Fetch data
            bars = self.data_client.get_crypto_bars(request)

            # Convert to Candle objects
            candles = []
            if pair in bars.data:
                for bar in bars.data[pair]:
                    candle = Candle(
                        timestamp=bar.timestamp,
                        open=float(bar.open),
                        high=float(bar.high),
                        low=float(bar.low),
                        close=float(bar.close),
                        volume=float(bar.volume),
                        pair=pair,  # Keep original format for consistency
                        timeframe=timeframe
                    )
                    candles.append(candle)

            logger.debug(f"Fetched {len(candles)} candles for {pair} ({timeframe})")
            return candles

        except Exception as e:
            logger.error(f"Error fetching OHLCV for {pair}: {e}")
            return []

    async def get_current_price(self, pair: str) -> float:
        """
        Get current price for a symbol.

        Args:
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            Current price as float
        """
        try:
            # Fetch recent 1-minute candles (get more to ensure data)
            candles = await self.fetch_ohlcv(pair, timeframe="1m", limit=5)
            if candles:
                return candles[-1].close
            raise ValueError(f"Could not fetch price for {pair}")
        except Exception as e:
            logger.error(f"Error fetching current price for {pair}: {e}")
            raise

    async def place_order(
        self,
        pair: str,
        side: str,
        order_type: str,
        amount: float,
        price: float = None
    ) -> Dict[str, Any]:
        """
        Place an order on Alpaca.

        Args:
            pair: Trading pair
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            amount: Order quantity
            price: Limit price (for limit orders)

        Returns:
            Order details
        """
        try:
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            if order_type == 'market':
                request = MarketOrderRequest(
                    symbol=pair,
                    qty=amount,
                    side=order_side,
                    time_in_force=TimeInForce.GTC
                )
            elif order_type == 'limit':
                if price is None:
                    raise ValueError("Price required for limit orders")
                request = LimitOrderRequest(
                    symbol=pair,
                    qty=amount,
                    side=order_side,
                    time_in_force=TimeInForce.GTC,
                    limit_price=price
                )
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

            order = self.trading_client.submit_order(request)

            logger.info(
                f"{order_type.upper()} order placed: {side} {amount} {pair} "
                f"(order_id={order.id})"
            )

            return {
                'id': str(order.id),
                'symbol': pair,
                'side': side,
                'type': order_type,
                'quantity': float(order.qty),
                'status': str(order.status),
                'filled_qty': float(order.filled_qty) if order.filled_qty else 0,
            }

        except Exception as e:
            logger.error(f"Error placing order: {e}")
            raise

    async def close(self):
        """Close Alpaca connection (no-op for Alpaca)."""
        logger.info("Alpaca connector closed")

    @property
    def is_connected(self) -> bool:
        """Check if connected (always True for Alpaca after initialization)."""
        return True

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
