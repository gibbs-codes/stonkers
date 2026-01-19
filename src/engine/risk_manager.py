"""Risk management system."""
from datetime import datetime, timedelta
from typing import Tuple, List
from src.data.models import Signal, Trade, Direction
from src.data.storage import Database
from src.config.settings import config


class RiskManager:
    """Risk management and position sizing."""

    def __init__(self, db: Database):
        """
        Initialize risk manager.

        Args:
            db: Database instance
        """
        self.db = db
        self.max_position_pct = config.get('risk.max_position_pct', 0.1)
        self.max_daily_loss_pct = config.get('risk.max_daily_loss_pct', 0.05)
        self.max_open_positions = config.get('risk.max_open_positions', 3)

        self._daily_pnl = 0.0
        self._last_reset = datetime.now().date()

    def calculate_position_size(
        self,
        signal: Signal,
        account_value: float,
        current_price: float
    ) -> float:
        """
        Calculate position size based on account percentage.

        Args:
            signal: Trading signal
            account_value: Total account value
            current_price: Current market price

        Returns:
            Position size in base currency (e.g., BTC quantity)
        """
        # Max position value based on account
        max_position_value = account_value * self.max_position_pct

        # Calculate quantity
        quantity = max_position_value / current_price

        return quantity

    def can_open_position(
        self,
        signal: Signal,
        current_positions: List,
        account_value: float,
        starting_balance: float
    ) -> Tuple[bool, str]:
        """
        Check if we can open a new position.

        Args:
            signal: Trading signal
            current_positions: List of currently open positions
            account_value: Current account value
            starting_balance: Starting balance for the day

        Returns:
            Tuple of (allowed, reason)
        """
        # Check if we already have a position for this pair
        for pos in current_positions:
            if pos.pair == signal.pair:
                return False, f"Already have open position for {signal.pair}"

        # Check daily loss limit
        daily_pnl_pct = ((account_value - starting_balance) / starting_balance) * 100
        if daily_pnl_pct <= -self.max_daily_loss_pct * 100:
            return False, f"Daily loss limit reached ({daily_pnl_pct:.2f}%)"

        # Check max open positions
        if len(current_positions) >= self.max_open_positions:
            return False, f"Max open positions ({self.max_open_positions}) reached"

        # Check if signal is actionable
        if not signal.is_actionable:
            return False, f"Signal strength too weak ({signal.strength})"

        return True, "Risk checks passed"

    def check_daily_limit(self, account_value: float, starting_balance: float) -> Tuple[bool, str]:
        """
        Check if daily loss limit has been hit.

        Args:
            account_value: Current account value
            starting_balance: Starting balance

        Returns:
            Tuple of (can_trade, reason)
        """
        daily_pnl_pct = ((account_value - starting_balance) / starting_balance) * 100

        if daily_pnl_pct <= -self.max_daily_loss_pct * 100:
            return False, f"Daily loss limit hit: {daily_pnl_pct:.2f}%"

        return True, "Within daily limits"

    def should_close_position(
        self,
        position,
        current_price: float,
        stop_loss_pct: float = 0.02,
        take_profit_pct: float = 0.05
    ) -> Tuple[bool, str]:
        """
        Check if position should be closed based on stop loss / take profit.

        Args:
            position: Open position
            current_price: Current market price
            stop_loss_pct: Stop loss percentage (default 2%)
            take_profit_pct: Take profit percentage (default 5%)

        Returns:
            Tuple of (should_close, reason)
        """
        pnl_pct = position.unrealized_pnl_pct(current_price)

        # Check stop loss
        if pnl_pct <= -stop_loss_pct * 100:
            return True, f"Stop loss hit: {pnl_pct:.2f}%"

        # Check take profit
        if pnl_pct >= take_profit_pct * 100:
            return True, f"Take profit hit: {pnl_pct:.2f}%"

        return False, ""

    def get_risk_metrics(self, account_value: float, starting_balance: float) -> dict:
        """
        Get current risk metrics.

        Args:
            account_value: Current account value
            starting_balance: Starting balance

        Returns:
            Dictionary of risk metrics
        """
        daily_pnl = account_value - starting_balance
        daily_pnl_pct = (daily_pnl / starting_balance) * 100
        daily_limit_remaining = (self.max_daily_loss_pct * 100) + daily_pnl_pct

        return {
            'daily_pnl': daily_pnl,
            'daily_pnl_pct': daily_pnl_pct,
            'daily_limit_remaining_pct': daily_limit_remaining,
            'max_position_pct': self.max_position_pct * 100,
            'max_open_positions': self.max_open_positions,
            'max_daily_loss_pct': self.max_daily_loss_pct * 100
        }
