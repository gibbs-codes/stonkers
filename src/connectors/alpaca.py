"""Alpaca connector for fetching market data."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List

from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from src.models.candle import Candle


class AlpacaConnector:
    """Connector for Alpaca crypto data API."""

    def __init__(self, api_key: str, secret_key: str, paper: bool = True):
        """Initialize Alpaca connector.

        Args:
            api_key: Alpaca API key
            secret_key: Alpaca secret key
            paper: Whether to use paper trading (default True)
        """
        self.client = CryptoHistoricalDataClient(api_key, secret_key)
        self.paper = paper

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
        bars = self.client.get_crypto_bars(request)

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
