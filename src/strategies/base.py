"""Base strategy class that all strategies inherit from."""
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Dict, List, Optional

from src.models.candle import Candle
from src.models.signal import Signal, ExitSignal


class Strategy(ABC):
    """Base class for all trading strategies.

    Strategies analyze candles and generate ENTRY signals.
    Strategies may also provide custom exit logic via should_exit().
    """

    def __init__(self, name: str):
        """Initialize strategy.

        Args:
            name: Strategy name for identification
        """
        self.name = name
        # Optional multi-timeframe filter flags; assigned post-init from config
        self.use_mtf_filter = False
        self.mtf_timeframe = "4h"
        # Market regime context, set by engine before analyze()
        self._current_regime = None

    @property
    def regime(self):
        """Current market regime (RangeAnalysis), set by the engine."""
        return self._current_regime

    @regime.setter
    def regime(self, value):
        self._current_regime = value

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

    def should_exit(self, position, candles: List[Candle], current_price: Decimal) -> Optional[ExitSignal]:
        """Check if position should be closed based on strategy-specific logic.

        Override in strategies that have custom exit logic.
        Default returns None (no strategy-level exit).

        Args:
            position: The open Position to evaluate
            candles: Recent candles for the position's pair
            current_price: Current market price

        Returns:
            ExitSignal if position should close, None otherwise
        """
        return None

    def diagnostics(self, candles: List[Candle]) -> Dict[str, str]:
        """Return a dict of current indicator values and condition statuses.

        Used for debugging why a strategy is not generating signals.
        Override in subclasses with strategy-specific diagnostics.

        Args:
            candles: List of recent candles

        Returns:
            Dict with human-readable key-value diagnostic info
        """
        return {"status": "no diagnostics implemented"}

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

    def check_mtf_alignment(self, signal: Signal, timestamp, mtf_context, timeframe: str = "4h") -> bool:
        """Return True if signal aligns with higher-timeframe trend or filter disabled."""
        if not getattr(self, "use_mtf_filter", False):
            return True
        if mtf_context is None:
            return True
        trend = mtf_context.get_trend(signal.pair, timestamp, timeframe=timeframe)
        if trend == "neutral":
            return False
        if signal.is_long and trend != "bullish":
            return False
        if signal.is_short and trend != "bearish":
            return False
        return True
