"""Candle data model with validation."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


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
