"""Alpaca connector for fetching market data and executing trades."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, TimeInForce
from alpaca.trading.requests import MarketOrderRequest

from src.models.candle import Candle


class AlpacaConnector:
    """Connector for Alpaca crypto data API and trading."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        """Initialize Alpaca connector.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Whether to use paper trading (default True)
        """
        self.data_client = CryptoHistoricalDataClient(api_key, secret_key)
        self.trading_client = TradingClient(api_key, secret_key, paper=paper)
        self.paper = paper

        # Keep backwards compatibility
        self.client = self.data_client

    def fetch_recent_candles(
        self,
        pairs: List[str],
        timeframe: TimeFrame = TimeFrame.Minute,
        limit: int = 200,
    ) -> Dict[str, List[Candle]]:
        """Fetch recent candles for given pairs.

        Args:
            pairs: List of trading pairs (e.g., ["BTC/USD", "ETH/USD"])
            timeframe: Timeframe for candles (default 1 minute)
            limit: Number of candles to fetch (default 200)

        Returns:
            Dict mapping pair -> list of Candles (oldest first)
        """
        # Calculate start/end times
        end = datetime.now(timezone.utc)

        # Calculate start time based on timeframe and limit
        # For simplicity, fetch last 24 hours
        start = end - timedelta(hours=24)

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

        except Exception as e:
            print(f"Error placing order: {e}")
            return None

    def get_open_positions(self) -> List:
        """Get all open positions.

        Returns:
            List of position objects
        """
        try:
            return self.trading_client.get_all_positions()
        except Exception as e:
            print(f"Error getting positions: {e}")
            return []

    def close_position(self, symbol: str) -> bool:
        """Close a position.

        Args:
            symbol: Trading symbol (e.g., "ETHUSD")

        Returns:
            True if successful, False otherwise
        """
        try:
            self.trading_client.close_position(symbol.replace("/", ""))
            return True
        except Exception as e:
            print(f"Error closing position: {e}")
            return False
