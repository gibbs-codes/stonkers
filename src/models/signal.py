"""Trading signal model."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, Any, Optional


class SignalType(Enum):
    """Signal types - entry only.

    Note: Strategies do NOT generate exit signals.
    Exits are handled by the engine based on risk rules.
    """
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"


@dataclass(frozen=True)
class Signal:
    """Trading signal from strategy analysis.

    Immutable to prevent modification after creation.
    Represents a potential trade opportunity identified by a strategy.
    """
    pair: str
    signal_type: SignalType
    strength: Decimal  # 0.0 to 1.0
    strategy_name: str
    reasoning: str
    timestamp: datetime  # From candle, for reference only
    indicators: Dict[str, Any]  # RSI, EMA values, etc.
    stop_loss_price: Optional[Decimal] = None  # Optional per-signal stop loss
    take_profit_price: Optional[Decimal] = None  # Optional per-signal take profit

    def __post_init__(self):
        """Validate signal data."""
        # Strength validation
        if not (Decimal("0") <= self.strength <= Decimal("1")):
            raise ValueError(f"Signal strength must be between 0 and 1, got: {self.strength}")

        # Timezone validation
        if not self.timestamp.tzinfo:
            raise ValueError("Signal timestamp must be timezone-aware")

        # Pair format
        if "/" not in self.pair:
            raise ValueError(f"Pair must be in format 'BASE/QUOTE', got: {self.pair}")

        # Reasoning required
        if not self.reasoning or not self.reasoning.strip():
            raise ValueError("Signal must include reasoning")

    @property
    def is_long(self) -> bool:
        """Check if signal is for LONG entry."""
        return self.signal_type == SignalType.ENTRY_LONG

    @property
    def is_short(self) -> bool:
        """Check if signal is for SHORT entry."""
        return self.signal_type == SignalType.ENTRY_SHORT
