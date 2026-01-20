"""Base strategy class that all strategies inherit from."""
from abc import ABC, abstractmethod
from typing import List, Optional

from src.models.candle import Candle
from src.models.signal import Signal


class Strategy(ABC):
    """Base class for all trading strategies.

    Strategies analyze candles and generate ENTRY signals only.
    Exit logic is handled by the engine via risk rules.
    """

    def __init__(self, name: str):
        """Initialize strategy.

        Args:
            name: Strategy name for identification
        """
        self.name = name

    @abstractmethod
    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles and generate signal if conditions met.

        Args:
            candles: List of recent candles (oldest first, newest last)

        Returns:
            Signal if entry conditions met, None otherwise

        Note:
            - Strategies should only return ENTRY signals (ENTRY_LONG or ENTRY_SHORT)
            - Return None if no entry signal (including NEUTRAL conditions)
            - Candles list should have enough history for indicator calculations
        """
        pass

    def _validate_candles(self, candles: List[Candle], min_required: int) -> bool:
        """Validate candles list has enough data.

        Args:
            candles: List of candles to validate
            min_required: Minimum number of candles needed

        Returns:
            True if sufficient candles, False otherwise
        """
        if not candles or len(candles) < min_required:
            return False

        # Validate all candles are for same pair
        if len(set(c.pair for c in candles)) > 1:
            raise ValueError("All candles must be for the same trading pair")

        return True
