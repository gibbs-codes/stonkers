"""Paper trader - executes simulated trades."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
import uuid

from src.data.database import Database
from src.models.position import Direction, Position, PositionStatus
from src.models.signal import Signal, SignalType


class PaperTrader:
    """Executes paper trades (simulation only).

    No real money involved - just updates database with simulated trades.
    """

    def __init__(
        self,
        db: Database,
        initial_balance: Decimal = Decimal("10000"),
        slippage_pct: Decimal = Decimal("0.001"),  # 0.1% default slippage
    ):
        """Initialize paper trader.

        Args:
            db: Database instance
            initial_balance: Starting cash balance
            slippage_pct: Slippage percentage to apply to fills
        """
        self.db = db
        self.initial_balance = initial_balance
        self.slippage_pct = slippage_pct
        self._initialize_account()

    def _initialize_account(self) -> None:
        """Initialize account state in database if not exists."""
        state = self.db.get_account_state()
        if not state:
            # First time - set initial balance
            self.db.save_account_state(
                cash=self.initial_balance,
                equity=self.initial_balance,
            )

    def _apply_slippage(self, price: Decimal, is_long: bool, is_exit: bool = False) -> Decimal:
        """Apply realistic slippage to fill price.

        Args:
            price: Base price before slippage
            is_long: Whether the position is long
            is_exit: Whether this is an exit (vs entry)

        Returns:
            Adjusted price with slippage (always worse for the trader)
        """
        # Determine if we're buying or selling
        if is_exit:
            is_buying = not is_long  # Long exit = sell, Short exit = buy
        else:
            is_buying = is_long  # Long entry = buy, Short entry = sell

        if is_buying:
            # Buying: pay more
            return price * (Decimal("1") + self.slippage_pct)
        else:
            # Selling: receive less
            return price * (Decimal("1") - self.slippage_pct)

    def get_account_value(self) -> Decimal:
        """Get current account equity.

        Returns:
            Current equity value
        """
        state = self.db.get_account_state()
        return state["equity"] if state else self.initial_balance

    def get_cash_balance(self) -> Decimal:
        """Get current cash balance.

        Returns:
            Current cash balance
        """
        state = self.db.get_account_state()
        return state["cash"] if state else self.initial_balance

    def log_signal(
        self,
        *,
        signal: Signal,
        status: str,
        rejection_reason: str | None = None,
        expected_entry_price: Decimal | None = None,
        actual_entry_price: Decimal | None = None,
        quantity: Decimal | None = None,
        position_id: str | None = None,
    ) -> int:
        """Persist signal decision for later analysis."""
        return self.db.insert_signal_log(
            timestamp=signal.timestamp,
            pair=signal.pair,
            strategy_name=signal.strategy_name,
            signal_type=signal.signal_type.value,
            strength=float(signal.strength),
            status=status,
            rejection_reason=rejection_reason,
            expected_entry_price=float(expected_entry_price) if expected_entry_price else None,
            actual_entry_price=float(actual_entry_price) if actual_entry_price else None,
            quantity=float(quantity) if quantity else None,
            slippage=float(actual_entry_price - expected_entry_price) if expected_entry_price and actual_entry_price else None,
            position_id=position_id,
        )

    def execute_entry(
        self,
        signal: Signal,
        entry_price: Decimal,
        quantity: Decimal,
        expected_entry_price: Decimal | None = None,
    ) -> Position:
        """Execute entry order (open new position).

        Args:
            signal: Trading signal
            entry_price: Base price to enter at (slippage will be applied)
            quantity: Quantity to trade

        Returns:
            Newly opened position
        """
        # Determine direction from signal type
        if signal.signal_type == SignalType.ENTRY_LONG:
            direction = Direction.LONG
            is_long = True
        elif signal.signal_type == SignalType.ENTRY_SHORT:
            direction = Direction.SHORT
            is_long = False
        else:
            raise ValueError(f"Invalid signal type for entry: {signal.signal_type}")

        # Apply slippage to get realistic fill price
        actual_entry_price = self._apply_slippage(entry_price, is_long=is_long, is_exit=False)

        # Create position with slippage-adjusted price
        position = Position(
            id=f"pos_{uuid.uuid4().hex[:8]}",
            pair=signal.pair,
            direction=direction,
            entry_price=actual_entry_price,
            quantity=quantity,
            entry_time=datetime.now(timezone.utc),  # Actual trade time, not signal time!
            strategy_name=signal.strategy_name,
            status=PositionStatus.OPEN,
            stop_loss_price=signal.stop_loss_price,
            take_profit_price=signal.take_profit_price,
            signal_id=None,
        )

        # Update cash (deduct position value with slippage-adjusted price)
        position_value = actual_entry_price * quantity
        cash = self.get_cash_balance()
        new_cash = cash - position_value

        if new_cash < 0:
            raise ValueError(
                f"Insufficient cash: have ${cash}, need ${position_value}"
            )

        # Fix: Calculate new equity correctly after position entry
        # Equity = new cash (after deduction) - we haven't gained or lost yet
        new_equity = new_cash  # At entry, equity = cash since unrealized P&L is 0
        self.db.save_account_state(cash=new_cash, equity=new_equity)

        # Log acceptance with actual/expected fills (includes slippage info)
        position.signal_id = self.log_signal(
            signal=signal,
            status="accepted",
            rejection_reason=None,
            expected_entry_price=expected_entry_price if expected_entry_price else entry_price,
            actual_entry_price=actual_entry_price,  # Price after slippage
            quantity=quantity,
            position_id=position.id,
        )

        return position

    def execute_exit(
        self,
        position: Position,
        exit_price: Decimal,
    ) -> Position:
        """Execute exit order (close position).

        Args:
            position: Position to close
            exit_price: Base price to exit at (slippage will be applied)

        Returns:
            Closed position with P&L calculated
        """
        # Apply slippage to exit price
        is_long = position.direction == Direction.LONG
        actual_exit_price = self._apply_slippage(exit_price, is_long=is_long, is_exit=True)

        # Calculate P&L with slippage-adjusted exit price
        pnl = position.unrealized_pnl(actual_exit_price)

        # Update cash: add back original position value + P&L
        cash = self.get_cash_balance()
        original_value = position.entry_price * position.quantity
        new_cash = cash + original_value + pnl

        # Equity after close = cash (no open positions from this trade)
        new_equity = new_cash

        self.db.save_account_state(cash=new_cash, equity=new_equity)

        # Log exit to signal_logs if available
        try:
            pnl_actual = float(pnl)
            pnl_expected = None
            if position.signal_id:
                self.db.update_signal_log_exit(
                    position_id=position.id,
                    actual_exit_price=float(actual_exit_price),  # Price after slippage
                    pnl_actual=pnl_actual,
                    pnl_expected=pnl_expected,
                    expected_exit_price=float(exit_price),  # Original price before slippage
                )
        except Exception:
            pass  # logging should never break trading

        return position

    def update_equity(self, unrealized_pnl: Decimal) -> None:
        """Update account equity with unrealized P&L.

        Args:
            unrealized_pnl: Total unrealized P&L from all positions
        """
        cash = self.get_cash_balance()
        equity = cash + unrealized_pnl

        self.db.save_account_state(cash=cash, equity=equity)
