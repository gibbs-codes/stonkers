"""Data fetching and caching."""
import asyncio
from datetime import datetime, timedelta
from typing import List
from src.connectors.base import ExchangeConnector
from src.data.models import Candle
from src.data.storage import Database
from src.config.settings import config


class DataFetcher:
    """Fetch and cache OHLCV data."""

    def __init__(self, connector: ExchangeConnector, db: Database):
        """
        Initialize data fetcher.

        Args:
            connector: Exchange connector (any implementation)
            db: Database instance
        """
        self.connector = connector
        self.db = db

    async def fetch_latest_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100
    ) -> List[Candle]:
        """
        Fetch latest candles, using cache when possible.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            limit: Number of candles to fetch

        Returns:
            List of Candle objects
        """
        # Fetch from exchange
        candles = await self.connector.fetch_ohlcv(
            pair=pair,
            timeframe=timeframe,
            limit=limit
        )

        if candles:
            # Store in database
            self.db.store_candles(candles)

        return candles

    async def fetch_historical_data(
        self,
        pair: str,
        timeframe: str,
        since: datetime,
        until: datetime = None
    ) -> List[Candle]:
        """
        Fetch historical candles for backtesting.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            since: Start datetime
            until: End datetime (default: now)

        Returns:
            List of Candle objects
        """
        if until is None:
            until = datetime.now()

        all_candles = []
        current_time = since

        # CCXT has limits on how much data per request
        # Fetch in chunks
        while current_time < until:
            candles = await self.connector.fetch_ohlcv(
                pair=pair,
                timeframe=timeframe,
                since=current_time,
                limit=1000
            )

            if not candles:
                break

            all_candles.extend(candles)

            # Move to next chunk
            current_time = candles[-1].timestamp + timedelta(seconds=1)

            # Respect rate limits
            await asyncio.sleep(0.5)

        # Store in database
        if all_candles:
            self.db.store_candles(all_candles)

        return all_candles

    def get_cached_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100
    ) -> List[Candle]:
        """
        Get candles from local database cache.

        Args:
            pair: Trading pair
            timeframe: Candle timeframe
            limit: Number of candles to retrieve

        Returns:
            List of Candle objects
        """
        return self.db.get_candles(pair, timeframe, limit)
