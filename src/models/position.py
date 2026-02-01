"""Position model with lifecycle state machine."""
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Optional


class PositionStatus(Enum):
    """Position lifecycle states."""
    OPEN = "open"
    CLOSED = "closed"


class Direction(Enum):
    """Trade direction."""
    LONG = "long"
    SHORT = "short"


@dataclass
class Position:
    """Trading position with explicit lifecycle.

    Positions are created OPEN and transition to CLOSED.
    Times are captured at actual trade execution, not from signals.
    """
    id: str
    pair: str
    direction: Direction
    entry_price: Decimal
    quantity: Decimal
    entry_time: datetime
    strategy_name: str
    status: PositionStatus = PositionStatus.OPEN
    exit_price: Optional[Decimal] = None
    exit_time: Optional[datetime] = None
    exit_reason: str = ""
    stop_loss_price: Optional[Decimal] = None
    take_profit_price: Optional[Decimal] = None
    signal_id: Optional[int] = None

    def __post_init__(self):
        """Validate position data."""
        # Timezone validation
        if not self.entry_time.tzinfo:
            raise ValueError("entry_time must be timezone-aware")

        if self.exit_time and not self.exit_time.tzinfo:
            raise ValueError("exit_time must be timezone-aware")

        # Status validation
        if self.status == PositionStatus.CLOSED:
            if not self.exit_time or not self.exit_price:
                raise ValueError("Closed position must have exit_time and exit_price")
            if self.exit_time < self.entry_time:
                raise ValueError("exit_time cannot be before entry_time")

        if self.status == PositionStatus.OPEN:
            if self.exit_time or self.exit_price:
                raise ValueError("Open position cannot have exit_time or exit_price")

        # Price validation
        if self.entry_price <= 0:
            raise ValueError("entry_price must be positive")

        if self.exit_price is not None and self.exit_price <= 0:
            raise ValueError("exit_price must be positive")

        if self.stop_loss_price is not None and self.stop_loss_price <= 0:
            raise ValueError("stop_loss_price must be positive")

        if self.take_profit_price is not None and self.take_profit_price <= 0:
            raise ValueError("take_profit_price must be positive")

        # Quantity validation
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")

    def close(self, exit_price: Decimal, reason: str) -> "Position":
        """Close position and return new closed Position.

        Returns new Position object (functional style).
        Original position is unchanged (immutable pattern).

        Args:
            exit_price: Price at which position was closed
            reason: Human-readable reason for closing

        Returns:
            New Position with CLOSED status

        Raises:
            ValueError: If position is already closed
        """
        if self.status == PositionStatus.CLOSED:
            raise ValueError(f"Position {self.id} is already closed")

        return replace(
            self,
            status=PositionStatus.CLOSED,
            exit_price=exit_price,
            exit_time=datetime.now(timezone.utc),
            exit_reason=reason
        )

    def unrealized_pnl(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L for open position.

        Args:
            current_price: Current market price

        Returns:
            Unrealized P&L in quote currency

        Raises:
            ValueError: If position is closed
        """
        if self.status == PositionStatus.CLOSED:
            raise ValueError("Cannot calculate unrealized P&L for closed position")

        if self.direction == Direction.LONG:
            return (current_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - current_price) * self.quantity

    def unrealized_pnl_pct(self, current_price: Decimal) -> Decimal:
        """Calculate unrealized P&L percentage.

        Args:
            current_price: Current market price

        Returns:
            Unrealized P&L as percentage of entry value
        """
        pnl = self.unrealized_pnl(current_price)
        entry_value = self.entry_price * self.quantity
        return (pnl / entry_value) * 100

    def realized_pnl(self) -> Decimal:
        """Calculate realized P&L for closed position.

        Returns:
            Realized P&L in quote currency

        Raises:
            ValueError: If position is not closed
        """
        if self.status != PositionStatus.CLOSED:
            raise ValueError("Cannot calculate realized P&L for open position")

        if self.direction == Direction.LONG:
            return (self.exit_price - self.entry_price) * self.quantity
        else:  # SHORT
            return (self.entry_price - self.exit_price) * self.quantity

    def realized_pnl_pct(self) -> Decimal:
        """Calculate realized P&L percentage.

        Returns:
            Realized P&L as percentage of entry value
        """
        pnl = self.realized_pnl()
        entry_value = self.entry_price * self.quantity
        return (pnl / entry_value) * 100

    def duration_seconds(self) -> float:
        """Get position duration in seconds.

        Returns:
            Duration in seconds

        Raises:
            ValueError: If position is not closed
        """
        if self.status != PositionStatus.CLOSED:
            raise ValueError("Cannot calculate duration for open position")

        return (self.exit_time - self.entry_time).total_seconds()

    def duration_minutes(self) -> float:
        """Get position duration in minutes."""
        return self.duration_seconds() / 60

    def duration_hours(self) -> float:
        """Get position duration in hours."""
        return self.duration_seconds() / 3600
