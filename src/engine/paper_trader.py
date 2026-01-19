"""Paper trading engine for simulating trades."""
import uuid
from datetime import datetime
from typing import Optional, List, Dict
from src.data.models import Signal, Trade, Position, Direction
from src.data.storage import Database
from src.config.settings import config


class PaperTrader:
    """Paper trading execution engine."""

    def __init__(self, db: Database):
        """
        Initialize paper trader.

        Args:
            db: Database instance for persistence
        """
        self.db = db
        self.slippage_pct = 0.001  # 0.1% slippage
        self.commission_pct = 0.001  # 0.1% commission per trade

        # Load or initialize state
        saved_balance, saved_starting = db.load_paper_trading_state()
        if saved_balance is not None:
            self.balance = saved_balance
            self.starting_balance = saved_starting
        else:
            self.starting_balance = config.get('paper_trading.starting_balance', 10000)
            self.balance = self.starting_balance
            self._save_state()

        # Load open positions
        self.positions: Dict[str, Position] = {}
        for pos in db.get_open_positions():
            self.positions[pos.id] = pos

    def _save_state(self):
        """Save current state to database."""
        self.db.save_paper_trading_state(self.balance, self.starting_balance)

    def execute_signal(
        self,
        signal: Signal,
        quantity: float,
        current_price: float
    ) -> Optional[Trade]:
        """
        Execute a signal by opening a position.

        Args:
            signal: Trading signal
            quantity: Position size (in base currency)
            current_price: Current market price

        Returns:
            None (position opened, not a completed trade yet)
        """
        if not signal.is_actionable:
            return None

        # Check if we already have a position for this pair
        existing_position = self._get_position_for_pair(signal.pair)
        if existing_position:
            # Don't open another position for same pair
            return None

        # Calculate entry price with slippage
        if signal.direction == Direction.LONG:
            entry_price = current_price * (1 + self.slippage_pct)
        else:  # SHORT
            entry_price = current_price * (1 - self.slippage_pct)

        # Calculate position value
        position_value = quantity * entry_price
        commission = position_value * self.commission_pct

        # Check if we have enough balance
        total_cost = position_value + commission
        if total_cost > self.balance:
            return None

        # Deduct from balance
        self.balance -= total_cost

        # Create position
        position = Position(
            id=str(uuid.uuid4()),
            pair=signal.pair,
            direction=signal.direction,
            entry_price=entry_price,
            quantity=quantity,
            entry_timestamp=signal.timestamp,
            strategy_name=signal.strategy_name
        )

        # Store position
        self.positions[position.id] = position
        self.db.store_position(position)
        self._save_state()

        return None  # Position opened, not a completed trade

    def close_position(
        self,
        position_id: str,
        current_price: float,
        reason: str = ""
    ) -> Optional[Trade]:
        """
        Close a position and record the trade.

        Args:
            position_id: Position ID
            current_price: Current market price
            reason: Reason for closing

        Returns:
            Trade object
        """
        if position_id not in self.positions:
            return None

        position = self.positions[position_id]

        # Calculate exit price with slippage
        if position.direction == Direction.LONG:
            exit_price = current_price * (1 - self.slippage_pct)
        else:  # SHORT
            exit_price = current_price * (1 + self.slippage_pct)

        # Calculate P&L
        if position.direction == Direction.LONG:
            pnl = (exit_price - position.entry_price) * position.quantity
        else:  # SHORT
            pnl = (position.entry_price - exit_price) * position.quantity

        # Subtract commission
        exit_value = position.quantity * exit_price
        commission = exit_value * self.commission_pct
        pnl -= (position.entry_price * position.quantity * self.commission_pct)  # Entry commission
        pnl -= commission  # Exit commission

        # Calculate P&L percentage
        pnl_pct = (pnl / (position.entry_price * position.quantity)) * 100

        # Add proceeds back to balance
        self.balance += (position.entry_price * position.quantity) + pnl

        # Create trade record
        trade = Trade(
            id=position.id,
            timestamp=datetime.now(),
            pair=position.pair,
            direction=position.direction,
            entry_price=position.entry_price,
            exit_price=exit_price,
            quantity=position.quantity,
            pnl=pnl,
            pnl_pct=pnl_pct,
            strategy_name=position.strategy_name,
            entry_timestamp=position.entry_timestamp,
            exit_timestamp=datetime.now(),
            exit_reason=reason,
            commission=commission
        )

        # Remove position
        del self.positions[position_id]
        self.db.close_position(position_id)
        self.db.store_trade(trade)
        self._save_state()

        return trade

    def close_position_by_pair(
        self,
        pair: str,
        current_price: float,
        reason: str = ""
    ) -> Optional[Trade]:
        """
        Close position for a specific pair.

        Args:
            pair: Trading pair
            current_price: Current market price
            reason: Reason for closing

        Returns:
            Trade object if position closed
        """
        position = self._get_position_for_pair(pair)
        if position:
            return self.close_position(position.id, current_price, reason)
        return None

    def _get_position_for_pair(self, pair: str) -> Optional[Position]:
        """Get open position for a pair."""
        for position in self.positions.values():
            if position.pair == pair:
                return position
        return None

    def get_portfolio_value(self, current_prices: Dict[str, float]) -> float:
        """
        Calculate total portfolio value (balance + positions).

        Args:
            current_prices: Dict of pair -> current price

        Returns:
            Total portfolio value
        """
        total_value = self.balance

        for position in self.positions.values():
            if position.pair in current_prices:
                current_price = current_prices[position.pair]
                unrealized_pnl = position.unrealized_pnl(current_price)
                position_value = (position.entry_price * position.quantity) + unrealized_pnl
                total_value += position_value

        return total_value

    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        return list(self.positions.values())

    def get_total_return_pct(self) -> float:
        """Get total return percentage."""
        return ((self.balance - self.starting_balance) / self.starting_balance) * 100

    @property
    def position_count(self) -> int:
        """Number of open positions."""
        return len(self.positions)
