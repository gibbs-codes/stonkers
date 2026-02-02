"""Historical crypto data manager for Alpaca."""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional

import pandas as pd
from alpaca.data.historical import CryptoHistoricalDataClient
from alpaca.data.requests import CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)

from src.models.candle import Candle


class HistoricalDataManager:
    """Fetches, caches, and validates historical OHLCV from Alpaca."""

    _TIMEFRAME_MAP: Dict[str, TimeFrame] = {
        "1m": TimeFrame(1, TimeFrameUnit.Minute),
        "5m": TimeFrame(5, TimeFrameUnit.Minute),
        "15m": TimeFrame(15, TimeFrameUnit.Minute),
        "1h": TimeFrame(1, TimeFrameUnit.Hour),
        "1d": TimeFrame(1, TimeFrameUnit.Day),
    }

    _TIMEFRAME_SECONDS: Dict[str, int] = {
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "1h": 3600,
        "1d": 86400,
    }

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        base_url: str = "https://data.alpaca.markets",
        data_dir: Path | str = Path("data/historical"),
        max_requests_per_minute: Optional[int] = 180,
        max_retries: int = 5,
        backoff_factor: float = 1.6,
        page_limit: int = 10000,
        data_client: Optional[CryptoHistoricalDataClient] = None,
        console: Optional[Console] = None,
        logger: Optional[logging.Logger] = None,
        storage_format: str = "parquet",
    ) -> None:
        """Create manager.

        Args:
            api_key: Alpaca API key (env recommended)
            secret_key: Alpaca API secret (env recommended)
            base_url: Alpaca data API base URL
            data_dir: Root folder for cached bar files
            max_requests_per_minute: Rate limit guard (None disables)
            max_retries: Retry attempts per request
            backoff_factor: Exponential backoff multiplier
            page_limit: Max bars per request (Alpaca caps at 10k)
            data_client: Optional pre-configured client (for tests)
            console: Rich console for progress output
            logger: Optional logger (uses module logger by default)
            storage_format: parquet or csv
        """

        self.logger = logger or logging.getLogger(__name__)
        self.console = console or Console(stderr=True)
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.max_requests_per_minute = max_requests_per_minute
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.page_limit = page_limit
        self.storage_format = storage_format

        # Sliding window timestamps for rate limiting
        self._request_times: deque = deque()

        self.data_client = data_client or CryptoHistoricalDataClient(
            api_key, secret_key, base_url=base_url
        )

    # Public API -----------------------------------------------------------------
    def fetch_bars(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        incremental: bool = True,
        storage_format: Optional[str] = None,
    ) -> pd.DataFrame:
        """Download bars for a symbol and cache to disk.

        Args:
            symbol: Trading pair (e.g., "BTC/USD")
            timeframe: String timeframe (1m, 5m, 15m, 1h, 1d)
            start: UTC start datetime
            end: UTC end datetime
            incremental: Only fetch data after cached max timestamp
            storage_format: Override file format (parquet|csv)

        Returns:
            Pandas DataFrame indexed by timestamp with OHLCV columns.
        """

        self._validate_inputs(symbol, timeframe, start, end)
        timeframe = timeframe.lower()
        fmt = (storage_format or self.storage_format).lower()
        cache_path = self._cache_path(symbol, timeframe, fmt)

        existing = self._load_cache(cache_path, fmt)
        effective_start = start

        if incremental and not existing.empty:
            last_ts = existing.index.max().to_pydatetime()
            effective_start = max(start, last_ts + timedelta(seconds=self._TIMEFRAME_SECONDS[timeframe]))
            if effective_start >= end:
                self.logger.info("Cache up-to-date for %s %s", symbol, timeframe)
                return existing

        records: List[dict] = []
        current_start = effective_start
        expected_total = self._estimate_expected_bars(start, end, timeframe)

        progress = self._build_progress()
        task_id = progress.add_task(
            f"{symbol} {timeframe}", total=expected_total if expected_total else None
        )

        with progress:
            while current_start < end:
                page_records = self._fetch_page(symbol, timeframe, current_start, end)
                if not page_records:
                    break

                records.extend(page_records)
                progress.update(task_id, advance=len(page_records))

                last_ts = page_records[-1]["timestamp"]
                current_start = last_ts + timedelta(seconds=self._TIMEFRAME_SECONDS[timeframe])

                # Guard against infinite loop if provider returns repeated bar
                if len(page_records) < self.page_limit:
                    # Probably reached the end
                    if current_start >= end:
                        break

        if not records and existing.empty:
            self.logger.warning("No data returned for %s %s", symbol, timeframe)
            return existing

        new_df = self._records_to_df(records, symbol)
        merged = self._merge_existing(existing, new_df)
        validated = self._validate_dataframe(merged, timeframe)
        self._save_cache(validated, cache_path, fmt)
        return validated

    def fetch_candles(
        self,
        symbols: Iterable[str],
        timeframe: str,
        start: datetime,
        end: datetime,
        incremental: bool = True,
        storage_format: Optional[str] = None,
    ) -> Dict[str, List[Candle]]:
        """Fetch bars for multiple symbols and convert to Candle objects."""

        candles: Dict[str, List[Candle]] = {}
        for symbol in symbols:
            df = self.fetch_bars(symbol, timeframe, start, end, incremental, storage_format)
            candles[symbol] = [
                Candle(
                    pair=symbol,
                    timestamp=idx.to_pydatetime(),
                    open=Decimal(str(row.open)),
                    high=Decimal(str(row.high)),
                    low=Decimal(str(row.low)),
                    close=Decimal(str(row.close)),
                    volume=Decimal(str(row.volume)),
                )
                for idx, row in df.iterrows()
            ]

        return candles

    # Internal helpers -----------------------------------------------------------
    def _fetch_page(
        self,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> List[dict]:
        """Fetch a single page of bars with retries and throttling."""

        tf = self._TIMEFRAME_MAP[timeframe]
        request = CryptoBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=tf,
            start=start,
            end=end,
            limit=self.page_limit,
        )

        response = self._with_retries(lambda: self.data_client.get_crypto_bars(request))

        if not response or symbol not in response.data:
            return []

        return [
            {
                "timestamp": bar.timestamp,
                "open": float(bar.open),
                "high": float(bar.high),
                "low": float(bar.low),
                "close": float(bar.close),
                "volume": float(bar.volume),
            }
            for bar in response.data[symbol]
        ]

    def _with_retries(self, fn: Callable):
        """Retry wrapper with exponential backoff and rate limiting."""

        for attempt in range(self.max_retries):
            self._throttle()
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                sleep_for = self.backoff_factor ** attempt
                jitter = 0.1 * sleep_for
                self.logger.warning(
                    "Request failed (attempt %s/%s): %s; sleeping %.2fs",
                    attempt + 1,
                    self.max_retries,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for + jitter)

        raise RuntimeError("Max retries exceeded while fetching bars")

    def _throttle(self) -> None:
        """Simple client-side rate limiter for Alpaca data API."""

        if not self.max_requests_per_minute:
            return

        now = time.monotonic()
        self._request_times.append(now)

        window_start = now - 60
        while self._request_times and self._request_times[0] < window_start:
            self._request_times.popleft()

        if len(self._request_times) > self.max_requests_per_minute:
            sleep_for = 60 - (now - self._request_times[0])
            if sleep_for > 0:
                self.logger.info("Throttling for %.2fs to respect rate limits", sleep_for)
                time.sleep(sleep_for)

    def _validate_inputs(self, symbol: str, timeframe: str, start: datetime, end: datetime) -> None:
        if timeframe.lower() not in self._TIMEFRAME_MAP:
            raise ValueError(f"Unsupported timeframe: {timeframe}")

        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("Start and end must be timezone-aware UTC datetimes")

        if start >= end:
            raise ValueError("Start must be before end")

        if "/" not in symbol:
            raise ValueError("Symbol must include '/' (e.g., BTC/USD)")

    def _cache_path(self, symbol: str, timeframe: str, fmt: str) -> Path:
        safe_symbol = symbol.replace("/", "-")
        folder = self.data_dir / timeframe
        folder.mkdir(parents=True, exist_ok=True)
        suffix = "parquet" if fmt == "parquet" else "csv"
        return folder / f"{safe_symbol}.{suffix}"

    def _load_cache(self, path: Path, fmt: str) -> pd.DataFrame:
        if not path.exists():
            return pd.DataFrame()

        if fmt == "parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, parse_dates=["timestamp"], index_col="timestamp")

        if "timestamp" in df.columns:
            df = df.set_index("timestamp")

        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index, utc=True)

        df = df.sort_index()
        return df

    def _save_cache(self, df: pd.DataFrame, path: Path, fmt: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if fmt == "parquet":
            df.to_parquet(path)
        else:
            df.reset_index().to_csv(path, index=False)

    def _merge_existing(self, existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
        if existing.empty:
            return new

        combined = pd.concat([existing, new])
        combined = combined[~combined.index.duplicated(keep="last")]
        return combined.sort_index()

    def _records_to_df(self, records: List[dict], symbol: str) -> pd.DataFrame:
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.set_index("timestamp").sort_index()
        df["pair"] = symbol
        return df

    def _validate_dataframe(self, df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
        if df.empty:
            return df

        df = df.sort_index()
        expected_delta = pd.Timedelta(seconds=self._TIMEFRAME_SECONDS[timeframe])

        duplicates = df.index.duplicated(keep="first")
        if duplicates.any():
            dup_count = duplicates.sum()
            self.logger.warning("Dropped %s duplicate bars", dup_count)
            df = df[~duplicates]

        gaps = df.index.to_series().diff().dropna()
        missing = gaps[gaps > expected_delta * 1.1]
        if not missing.empty:
            largest_gap = missing.max()
            self.logger.warning("Detected gaps up to %s in %s data", largest_gap, timeframe)

        return df

    def _estimate_expected_bars(self, start: datetime, end: datetime, timeframe: str) -> Optional[int]:
        seconds = (end - start).total_seconds()
        tf_seconds = self._TIMEFRAME_SECONDS.get(timeframe)
        if not tf_seconds:
            return None
        return math.ceil(seconds / tf_seconds)

    def _build_progress(self) -> Progress:
        return Progress(
            SpinnerColumn(),
            TextColumn("{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            TimeRemainingColumn(),
            console=self.console,
            transient=True,
        )

