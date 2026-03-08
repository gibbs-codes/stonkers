"""Candle data model with validation."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Candle:
    """OHLCV candle with strict validation.

    Immutable to prevent accidental modification.
    All prices are Decimal for precision.
    Timestamp must be timezone-aware.
    """
    pair: str
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def __post_init__(self):
        """Validate candle data."""
        # Timezone validation
        if not self.timestamp.tzinfo:
            raise ValueError("Candle timestamp must be timezone-aware")

        # Positive values (check this FIRST before relationships)
        if self.open <= 0 or self.high <= 0 or self.low <= 0 or self.close <= 0:
            raise ValueError("All prices must be positive")

        if self.volume < 0:
            raise ValueError("Volume cannot be negative")

        # Price relationships (now we know all values are positive)
        if self.high < self.low:
            raise ValueError(f"High ({self.high}) cannot be less than low ({self.low})")

        if self.high < self.open or self.high < self.close:
            raise ValueError(f"High ({self.high}) must be >= open ({self.open}) and close ({self.close})")

        if self.low > self.open or self.low > self.close:
            raise ValueError(f"Low ({self.low}) must be <= open ({self.open}) and close ({self.close})")

        # Pair format
        if "/" not in self.pair:
            raise ValueError(f"Pair must be in format 'BASE/QUOTE', got: {self.pair}")

    @classmethod
    def from_alpaca(cls, bar, pair: str) -> "Candle":
        """Create Candle from Alpaca Bar object.

        Args:
            bar: Alpaca Bar object
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            Candle instance
        """
        return cls(
            pair=pair,
            timestamp=bar.timestamp,  # Alpaca timestamps are timezone-aware
            open=Decimal(str(bar.open)),
            high=Decimal(str(bar.high)),
            low=Decimal(str(bar.low)),
            close=Decimal(str(bar.close)),
            volume=Decimal(str(bar.volume))
        )

    @staticmethod
    def validate_continuity(
        candles: List["Candle"],
        expected_interval_minutes: int = 15,
        max_allowed_gaps: int = 2,
    ) -> Tuple[bool, List[Tuple[datetime, datetime]]]:
        """Validate that candles are continuous without gaps.

        Args:
            candles: List of candles to validate (should be sorted by timestamp)
            expected_interval_minutes: Expected time between candles (default 15)
            max_allowed_gaps: Maximum number of gaps to tolerate (default 2)

        Returns:
            Tuple of (is_valid, list of gap tuples [(gap_start, gap_end), ...])
        """
        if len(candles) < 2:
            return True, []

        expected_delta = timedelta(minutes=expected_interval_minutes)
        # Allow some tolerance (e.g., 10% of interval)
        tolerance = timedelta(minutes=expected_interval_minutes * 0.1)

        gaps = []
        for i in range(1, len(candles)):
            actual_delta = candles[i].timestamp - candles[i - 1].timestamp

            # Check if gap is larger than expected (with tolerance)
            if actual_delta > expected_delta + tolerance:
                gaps.append((candles[i - 1].timestamp, candles[i].timestamp))
                logger.warning(
                    f"Candle gap detected: {candles[i-1].timestamp} -> {candles[i].timestamp} "
                    f"(expected {expected_delta}, got {actual_delta})"
                )

        is_valid = len(gaps) <= max_allowed_gaps
        if not is_valid:
            logger.error(
                f"Too many candle gaps ({len(gaps)} > {max_allowed_gaps}). "
                f"Data may be corrupt or incomplete."
            )

        return is_valid, gaps
