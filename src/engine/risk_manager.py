"""Risk manager - pure functions for risk checks."""
from decimal import Decimal
from typing import Dict, Optional

from src.models.position import Position
from src.models.signal import Signal


class RiskManager:
    """Manages risk rules and position sizing.

    Pure functions - no state, no side effects.
    All decisions based on inputs only.
    """

    def __init__(
        self,
        max_positions: int = 5,
        max_position_size_pct: Decimal = Decimal("0.2"),  # 20% per position
        stop_loss_pct: Decimal = Decimal("0.02"),  # 2% stop loss
        take_profit_pct: Decimal = Decimal("0.05"),  # 5% take profit
    ):
        """Initialize risk manager.

        Args:
            max_positions: Maximum concurrent positions
            max_position_size_pct: Max % of portfolio per position (0.0 to 1.0)
            stop_loss_pct: Stop loss percentage (0.0 to 1.0)
            take_profit_pct: Take profit percentage (0.0 to 1.0)
        """
        self.max_positions = max_positions
        self.max_position_size_pct = max_position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct

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

        # Rule 3: Signal strength threshold (must be > 0.5)
        if signal.strength <= Decimal("0.5"):
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
