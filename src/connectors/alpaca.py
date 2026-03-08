"""Alpaca connector for fetching market data and executing trades."""
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest
from alpaca.common.exceptions import APIError

from src.models.candle import Candle

logger = logging.getLogger(__name__)


class AlpacaConnectionError(Exception):
    """Raised when Alpaca API connection fails."""
    pass


class AlpacaOrderError(Exception):
    """Raised when order placement fails."""
    pass


class AlpacaConnector:
    """Connector for Alpaca crypto data API and trading."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        """Initialize Alpaca connector.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Whether to use paper trading (default True)

        Raises:
            ValueError: If API keys are empty
            AlpacaConnectionError: If connection test fails
        """
        if not api_key or not secret_key:
            raise ValueError("Alpaca API key and secret key are required")

        self.data_client = CryptoHistoricalDataClient(api_key, secret_key)
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.paper = paper

        # Keep backwards compatibility
        self.client = self.data_client

        # Test connection on init
        try:
            self.trading_client.get_account()
            logger.info(f"Alpaca connector initialized (paper={paper})")
        except APIError as e:
            raise AlpacaConnectionError(f"Failed to connect to Alpaca: {e}")

    def fetch_recent_candles(
        self,
        pairs: List[str],
        timeframe: TimeFrame = None,
        limit: int = 200,
        days_back: int = 30,
    ) -> Dict[str, List[Candle]]:
        """Fetch recent candles for given pairs.

        Args:
            pairs: List of trading pairs (e.g., ["BTC/USD", "ETH/USD"])
            timeframe: Timeframe for candles (default 15 minutes)
            limit: Number of candles to fetch (default 200)
            days_back: How many days of history to request (default 30)

        Returns:
            Dict mapping pair -> list of Candles (oldest first)
        """
        # Default to 15-minute candles
        if timeframe is None:
            timeframe = TimeFrame(15, TimeFrameUnit.Minute)

        # Calculate start/end times
        end = datetime.now(timezone.utc)

        # Calculate start time based on requested days_back
        # Keep within provider limits via limit param supplied by caller
        start = end - timedelta(days=days_back)

        # Build request
        request = CryptoBarsRequest(
            symbol_or_symbols=pairs,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )

        # Fetch bars
        bars = self.data_client.get_crypto_bars(request)

        # Convert to Candles grouped by pair
        result = {}
        for pair in pairs:
            if pair not in bars.data:
                result[pair] = []
                continue

            pair_bars = bars.data[pair]
            candles = [
                Candle(
                    pair=pair,
                    timestamp=bar.timestamp,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=Decimal(str(bar.volume)),
                )
                for bar in pair_bars
            ]

            # Sort by timestamp (oldest first)
            candles.sort(key=lambda c: c.timestamp)

            # Limit to requested number
            result[pair] = candles[-limit:]

        return result

    def get_latest_price(self, pair: str) -> Decimal:
        """Get latest price for a pair.

        Args:
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            Latest price as Decimal
        """
        candles = self.fetch_recent_candles([pair], limit=1)
        if not candles.get(pair):
            raise ValueError(f"No data available for {pair}")

        return candles[pair][-1].close

    def get_account(self):
        """Get account information.

        Returns:
            Account object with balance, equity, etc.
        """
        return self.trading_client.get_account()

    def place_market_order(
        self,
        symbol: str,
        qty: Decimal,
        side: str
    ) -> Optional[dict]:
        """Place a market order.

        Args:
            symbol: Trading symbol (e.g., "ETHUSD" - no slash for orders)
            qty: Quantity to trade
            side: "buy" or "sell"

        Returns:
            Order object if successful, None if failed
        """
        try:
            # Convert side string to OrderSide enum
            order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL

            # Create market order request
            order_request = MarketOrderRequest(
                symbol=symbol.replace("/", ""),  # Remove slash: "ETH/USD" -> "ETHUSD"
                qty=float(qty),
                side=order_side,
                time_in_force=TimeInForce.GTC,  # Good till canceled
            )

            # Submit order
            order = self.trading_client.submit_order(order_request)
            return order

        except APIError as e:
            logger.error(f"Alpaca API error placing order for {symbol}: {e}")
            raise AlpacaOrderError(f"Failed to place order: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error placing order for {symbol}: {e}")
            raise AlpacaOrderError(f"Unexpected error placing order: {e}")

    def get_open_positions(self) -> List:
        """Get all open positions.

        Returns:
            List of position objects

        Raises:
            AlpacaConnectionError: If API call fails
        """
        try:
            return self.trading_client.get_all_positions()
        except APIError as e:
            logger.error(f"Alpaca API error getting positions: {e}")
            raise AlpacaConnectionError(f"Failed to get positions: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error getting positions: {e}")
            raise AlpacaConnectionError(f"Unexpected error getting positions: {e}")

    def close_position(self, symbol: str) -> bool:
        """Close a position.

        Args:
            symbol: Trading symbol (e.g., "ETHUSD")

        Returns:
            True if successful

        Raises:
            AlpacaOrderError: If position close fails
        """
        try:
            self.trading_client.close_position(symbol.replace("/", ""))
            logger.info(f"Successfully closed position for {symbol}")
            return True
        except APIError as e:
            logger.error(f"Alpaca API error closing position {symbol}: {e}")
            raise AlpacaOrderError(f"Failed to close position: {e}")
        except Exception as e:
            logger.exception(f"Unexpected error closing position {symbol}: {e}")
            raise AlpacaOrderError(f"Unexpected error closing position: {e}")
