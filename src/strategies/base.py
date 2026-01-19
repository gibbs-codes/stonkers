"""Base strategy interface."""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from src.data.models import Candle, Signal


class Strategy(ABC):
    """Base class for all trading strategies."""

    name: str = ""  # Unique identifier
    description: str = ""  # Human-readable description
    required_history: int = 100  # Minimum candles needed

    def __init__(self):
        """Initialize strategy."""
        self.params: Dict[str, Any] = {}

    @abstractmethod
    def configure(self, params: dict) -> None:
        """
        Load strategy-specific parameters from config.

        Args:
            params: Strategy parameters dictionary
        """
        pass

    @abstractmethod
    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """
        Analyze candles and optionally generate a signal.

        MUST include reasoning in the Signal explaining WHY
        the signal was generated (or log why not, via return None).

        Args:
            candles: List of historical candles (newest last)

        Returns:
            Signal object if conditions met, None otherwise
        """
        pass

    @abstractmethod
    def get_default_params(self) -> dict:
        """
        Return default parameters for this strategy.

        Returns:
            Dictionary of default parameter values
        """
        pass

    def validate_candles(self, candles: List[Candle]) -> bool:
        """
        Check if we have enough candles for analysis.

        Args:
            candles: List of candles

        Returns:
            True if sufficient data available
        """
        return len(candles) >= self.required_history

    def __repr__(self) -> str:
        """String representation of strategy."""
        return f"{self.name}(params={self.params})"
