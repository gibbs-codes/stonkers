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
        use_fixed_position_sizing: bool = False,  # If True, use initial equity for sizing
        initial_equity: Optional[Decimal] = None,  # Starting equity for fixed sizing
    ):
        """Initialize risk manager.

        Args:
            max_positions: Maximum concurrent positions
            max_position_size_pct: Max % of portfolio per position (0.0 to 1.0)
            stop_loss_pct: Stop loss percentage (0.0 to 1.0)
            take_profit_pct: Take profit percentage (0.0 to 1.0)
            trailing_stop_pct: Trailing stop percentage (None to disable)
            use_fixed_position_sizing: If True, size positions based on initial equity
                                       to prevent death spiral during drawdowns
            initial_equity: Starting equity to use for fixed sizing (required if use_fixed_position_sizing=True)
        """
        self.max_positions = max_positions
        self.max_position_size_pct = max_position_size_pct
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.trailing_stop_pct = trailing_stop_pct
        # High-water marks for trailing stops (position_id -> best price)
        self._high_water_marks: Dict[str, Decimal] = {}
        self.use_fixed_position_sizing = use_fixed_position_sizing
        self.initial_equity = initial_equity
        self._high_water_mark: Optional[Decimal] = initial_equity

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
        # Update high water mark if current equity is higher
        if self._high_water_mark is None:
            self._high_water_mark = account_value
        elif account_value > self._high_water_mark:
            self._high_water_mark = account_value

        # Choose sizing basis: fixed (initial/HWM) or dynamic (current equity)
        if self.use_fixed_position_sizing and self.initial_equity is not None:
            # Use initial equity to prevent death spiral
            # Position sizes stay constant regardless of drawdown
            sizing_basis = self.initial_equity
        else:
            # Standard dynamic sizing based on current equity
            sizing_basis = account_value

        # Position value = sizing_basis * max_position_size_pct
        position_value = sizing_basis * self.max_position_size_pct

        # Safety check: don't size larger than current account can afford
        max_affordable = account_value * Decimal("0.95")  # Leave 5% buffer
        position_value = min(position_value, max_affordable)

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
        candle_high: Optional[Decimal] = None,
        candle_low: Optional[Decimal] = None,
    ) -> tuple[bool, str]:
        """Check if position should be closed based on risk rules.

        Args:
            position: Open position to check
            current_price: Current market price (candle close)
            candle_high: High of current candle (for intra-candle stop checks)
            candle_low: Low of current candle (for intra-candle stop checks)

        Returns:
            Tuple of (should_close: bool, reason: str)
        """
        # Use candle extremes for stop loss checks (catches intra-candle stop hits)
        # For longs: stop loss triggered if price went DOWN to stop (use candle low)
        # For shorts: stop loss triggered if price went UP to stop (use candle high)
        stop_check_price_long = candle_low if candle_low is not None else current_price
        stop_check_price_short = candle_high if candle_high is not None else current_price

        # Strategy-specific stop/take precedence when provided
        if position.stop_loss_price:
            if position.direction == Direction.LONG and stop_check_price_long <= position.stop_loss_price:
                return True, f"Per-signal stop loss hit (low {stop_check_price_long} <= {position.stop_loss_price})"
            if position.direction == Direction.SHORT and stop_check_price_short >= position.stop_loss_price:
                return True, f"Per-signal stop loss hit (high {stop_check_price_short} >= {position.stop_loss_price})"

        if position.take_profit_price:
            # For take profit, use the favorable extreme:
            # Longs profit when price goes UP (use candle high)
            # Shorts profit when price goes DOWN (use candle low)
            tp_check_price_long = candle_high if candle_high is not None else current_price
            tp_check_price_short = candle_low if candle_low is not None else current_price

            if position.direction == Direction.LONG and tp_check_price_long >= position.take_profit_price:
                return True, f"Per-signal take profit hit (high {tp_check_price_long} >= {position.take_profit_price})"
            if position.direction == Direction.SHORT and tp_check_price_short <= position.take_profit_price:
                return True, f"Per-signal take profit hit (low {tp_check_price_short} <= {position.take_profit_price})"

        # Trailing stop check (from remote)
        trailing_hit, trailing_reason = self.check_trailing_stop(position, current_price)
        if trailing_hit:
            return True, trailing_reason

        # Calculate P&L percentage using worst-case price for stops
        if position.direction == Direction.LONG:
            worst_price = stop_check_price_long
            best_price = candle_high if candle_high is not None else current_price
        else:
            worst_price = stop_check_price_short
            best_price = candle_low if candle_low is not None else current_price

        # Check stop loss using worst intra-candle price
        pnl_worst = position.unrealized_pnl(worst_price)
        pnl_pct_worst = pnl_worst / (position.entry_price * position.quantity)

        if pnl_pct_worst <= -self.stop_loss_pct:
            return True, f"Stop loss hit ({pnl_pct_worst:.2%} at {worst_price})"

        # Check take profit using best intra-candle price
        pnl_best = position.unrealized_pnl(best_price)
        pnl_pct_best = pnl_best / (position.entry_price * position.quantity)

        if pnl_pct_best >= self.take_profit_pct:
            return True, f"Take profit hit ({pnl_pct_best:.2%} at {best_price})"

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
