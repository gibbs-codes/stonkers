"""Risk manager - risk checks and trailing stop tracking."""
from decimal import Decimal
from typing import Dict, Optional

from src.models.position import Position, Direction
from src.models.signal import Signal


class RiskManager:
    """Manages risk rules, position sizing, and trailing stops."""

    def __init__(
        self,
        max_positions: int = 5,
        max_position_size_pct: Decimal = Decimal("0.2"),  # 20% per position
        stop_loss_pct: Decimal = Decimal("0.02"),  # 2% stop loss
        take_profit_pct: Decimal = Decimal("0.05"),  # 5% take profit
        trailing_stop_pct: Optional[Decimal] = None,  # e.g., 0.015 = 1.5%
    ):
        """Initialize risk manager.

        Args:
            max_positions: Maximum concurrent positions
            max_position_size_pct: Max % of portfolio per position (0.0 to 1.0)
            stop_loss_pct: Stop loss percentage (0.0 to 1.0)
            take_profit_pct: Take profit percentage (0.0 to 1.0)
            trailing_stop_pct: Trailing stop percentage (None to disable)
        """
        self.max_positions = max_positions
        self.max_position_size_pct = max_position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        # High-water marks for trailing stops (position_id -> best price)
        self._high_water_marks: Dict[str, Decimal] = {}

    def can_open_position(
        self,
        signal: Signal,
        open_positions_count: int,
        has_position_for_pair: bool,
    ) -> tuple[bool, str]:
        """Check if signal passes all risk rules.

        Args:
            signal: Trading signal to evaluate
            open_positions_count: Current number of open positions
            has_position_for_pair: Whether pair already has position

        Returns:
            Tuple of (can_open: bool, reason: str)
        """
        # Rule 1: No duplicate positions per pair
        if has_position_for_pair:
            return False, f"Already have position for {signal.pair}"

        # Rule 2: Max concurrent positions
        if open_positions_count >= self.max_positions:
            return False, f"Already at max positions ({self.max_positions})"

        # Rule 3: Signal strength threshold (allows slightly weaker but still valid signals)
        if signal.strength <= Decimal("0.4"):
            return False, f"Signal strength too weak ({signal.strength})"

        return True, "All risk checks passed"

    def calculate_position_size(
        self,
        account_value: Decimal,
        entry_price: Decimal,
    ) -> Decimal:
        """Calculate position size based on risk parameters.

        Args:
            account_value: Total account value
            entry_price: Price to enter at

        Returns:
            Quantity to trade
        """
        # Position value = account_value * max_position_size_pct
        position_value = account_value * self.max_position_size_pct

        # Quantity = position_value / entry_price
        quantity = position_value / entry_price

        return quantity

    def update_high_water_mark(self, position: Position, current_price: Decimal) -> None:
        """Update the high-water mark for trailing stop calculation."""
        pos_id = position.id
        if position.direction == Direction.LONG:
            if pos_id not in self._high_water_marks or current_price > self._high_water_marks[pos_id]:
                self._high_water_marks[pos_id] = current_price
        else:  # SHORT — track lowest price
            if pos_id not in self._high_water_marks or current_price < self._high_water_marks[pos_id]:
                self._high_water_marks[pos_id] = current_price

    def check_trailing_stop(self, position: Position, current_price: Decimal) -> tuple[bool, str]:
        """Check if trailing stop is hit."""
        if not self.trailing_stop_pct:
            return False, ""

        pos_id = position.id
        if pos_id not in self._high_water_marks:
            return False, ""

        hwm = self._high_water_marks[pos_id]

        if position.direction == Direction.LONG:
            trail_price = hwm * (Decimal("1") - self.trailing_stop_pct)
            if current_price <= trail_price:
                return True, f"Trailing stop hit (HWM: ${hwm:.2f}, trail: ${trail_price:.2f})"
        else:  # SHORT
            trail_price = hwm * (Decimal("1") + self.trailing_stop_pct)
            if current_price >= trail_price:
                return True, f"Trailing stop hit (HWM: ${hwm:.2f}, trail: ${trail_price:.2f})"

        return False, ""

    def clear_position_state(self, position_id: str) -> None:
        """Clean up tracking state when a position is closed."""
        self._high_water_marks.pop(position_id, None)

    def should_close_position(
        self,
        position: Position,
        current_price: Decimal,
    ) -> tuple[bool, str]:
        """Check if position should be closed based on risk rules.

        Args:
            position: Open position to check
            current_price: Current market price

        Returns:
            Tuple of (should_close: bool, reason: str)
        """
        # Strategy-specific stop/take precedence when provided
        if position.stop_loss_price:
            if position.direction == Direction.LONG and current_price <= position.stop_loss_price:
                return True, f"Per-signal stop loss hit ({current_price} <= {position.stop_loss_price})"
            if position.direction == Direction.SHORT and current_price >= position.stop_loss_price:
                return True, f"Per-signal stop loss hit ({current_price} >= {position.stop_loss_price})"

        if position.take_profit_price:
            if position.direction == Direction.LONG and current_price >= position.take_profit_price:
                return True, f"Per-signal take profit hit ({current_price} >= {position.take_profit_price})"
            if position.direction == Direction.SHORT and current_price <= position.take_profit_price:
                return True, f"Per-signal take profit hit ({current_price} <= {position.take_profit_price})"

        # Trailing stop check
        trailing_hit, trailing_reason = self.check_trailing_stop(position, current_price)
        if trailing_hit:
            return True, trailing_reason

        # Calculate P&L percentage
        pnl = position.unrealized_pnl(current_price)
        pnl_pct = pnl / (position.entry_price * position.quantity)

        # Stop loss check
        if pnl_pct <= -self.stop_loss_pct:
            return True, f"Stop loss hit ({pnl_pct:.2%})"

        # Take profit check
        if pnl_pct >= self.take_profit_pct:
            return True, f"Take profit hit ({pnl_pct:.2%})"

        return False, "No exit conditions met"

    def get_total_exposure_pct(
        self,
        total_exposure: Decimal,
        account_value: Decimal,
    ) -> Decimal:
        """Calculate total exposure as percentage of account.

        Args:
            total_exposure: Total value of all open positions
            account_value: Total account value

        Returns:
            Exposure percentage (0.0 to 1.0+)
        """
        if account_value <= 0:
            return Decimal("0")

        return total_exposure / account_value
