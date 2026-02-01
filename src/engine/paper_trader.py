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

    def __init__(self, db: Database, initial_balance: Decimal = Decimal("10000")):
        """Initialize paper trader.

        Args:
            db: Database instance
            initial_balance: Starting cash balance
        """
        self.db = db
        self.initial_balance = initial_balance
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
            entry_price: Price to enter at
            quantity: Quantity to trade

        Returns:
            Newly opened position
        """
        # Determine direction from signal type
        if signal.signal_type == SignalType.ENTRY_LONG:
            direction = Direction.LONG
        elif signal.signal_type == SignalType.ENTRY_SHORT:
            direction = Direction.SHORT
        else:
            raise ValueError(f"Invalid signal type for entry: {signal.signal_type}")

        # Create position
        position = Position(
            id=f"pos_{uuid.uuid4().hex[:8]}",
            pair=signal.pair,
            direction=direction,
            entry_price=entry_price,
            quantity=quantity,
            entry_time=datetime.now(timezone.utc),  # Actual trade time, not signal time!
            strategy_name=signal.strategy_name,
            status=PositionStatus.OPEN,
            stop_loss_price=signal.stop_loss_price,
            take_profit_price=signal.take_profit_price,
            signal_id=None,
        )

        # Update cash (deduct position value)
        position_value = entry_price * quantity
        cash = self.get_cash_balance()
        new_cash = cash - position_value

        if new_cash < 0:
            raise ValueError(
                f"Insufficient cash: have ${cash}, need ${position_value}"
            )

        self.db.save_account_state(cash=new_cash, equity=self.get_account_value())

        # Log acceptance with actual/expected fills
        position.signal_id = self.log_signal(
            signal=signal,
            status="accepted",
            rejection_reason=None,
            expected_entry_price=expected_entry_price,
            actual_entry_price=entry_price,
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
            exit_price: Price to exit at

        Returns:
            Closed position with P&L calculated
        """
        # Calculate P&L
        pnl = position.unrealized_pnl(exit_price)

        # Update cash: add back original position value + P&L
        cash = self.get_cash_balance()
        original_value = position.entry_price * position.quantity
        new_cash = cash + original_value + pnl

        # Update equity
        equity = self.get_account_value()
        new_equity = equity + pnl

        self.db.save_account_state(cash=new_cash, equity=new_equity)

        # Log exit to signal_logs if available
        try:
            pnl_actual = float(pnl)
            pnl_expected = None
            if position.signal_id:
                self.db.update_signal_log_exit(
                    position_id=position.id,
                    actual_exit_price=float(exit_price),
                    pnl_actual=pnl_actual,
                    pnl_expected=pnl_expected,
                    expected_exit_price=None,
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
