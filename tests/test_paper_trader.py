"""Tests for paper trader."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import tempfile

import pytest

from src.data.database import Database
from src.engine.paper_trader import PaperTrader
from src.models.position import Direction, Position, PositionStatus
from src.models.signal import Signal, SignalType


@pytest.fixture
def db():
    """Create temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        yield Database(Path(f.name))


@pytest.fixture
def paper_trader(db):
    """Create paper trader with $10,000 starting balance."""
    return PaperTrader(db, initial_balance=Decimal("10000"))


@pytest.fixture
def long_signal():
    """Create long entry signal."""
    return Signal(
        pair="BTC/USD",
        signal_type=SignalType.ENTRY_LONG,
        strength=Decimal("0.8"),
        strategy_name="test_strategy",
        reasoning="Bullish",
        timestamp=datetime.now(timezone.utc),
        indicators={},
    )


@pytest.fixture
def short_signal():
    """Create short entry signal."""
    return Signal(
        pair="ETH/USD",
        signal_type=SignalType.ENTRY_SHORT,
        strength=Decimal("0.7"),
        strategy_name="test_strategy",
        reasoning="Bearish",
        timestamp=datetime.now(timezone.utc),
        indicators={},
    )


class TestAccountInitialization:
    """Test account setup."""

    def test_initializes_with_starting_balance(self, paper_trader):
        """Should start with configured balance."""
        assert paper_trader.get_account_value() == Decimal("10000")
        assert paper_trader.get_cash_balance() == Decimal("10000")

    def test_persists_account_state_to_db(self, db):
        """Should save account state to database."""
        trader = PaperTrader(db, initial_balance=Decimal("5000"))

        # Check it's in database
        state = db.get_account_state()
        assert state["cash"] == Decimal("5000")
        assert state["equity"] == Decimal("5000")


class TestExecuteEntry:
    """Test opening positions."""

    def test_opens_long_position(self, paper_trader, long_signal):
        """Should open long position and deduct cash."""
        entry_price = Decimal("50000")
        quantity = Decimal("0.1")

        position = paper_trader.execute_entry(long_signal, entry_price, quantity)

        # Check position
        assert position.direction == Direction.LONG
        assert position.pair == "BTC/USD"
        assert position.entry_price == entry_price
        assert position.quantity == quantity
        assert position.status == PositionStatus.OPEN

        # Check cash deducted
        # $50,000 * 0.1 = $5,000
        # $10,000 - $5,000 = $5,000
        assert paper_trader.get_cash_balance() == Decimal("5000")

    def test_opens_short_position(self, paper_trader, short_signal):
        """Should open short position."""
        entry_price = Decimal("3000")
        quantity = Decimal("1.0")

        position = paper_trader.execute_entry(short_signal, entry_price, quantity)

        assert position.direction == Direction.SHORT
        assert position.pair == "ETH/USD"

        # Cash: $10,000 - $3,000 = $7,000
        assert paper_trader.get_cash_balance() == Decimal("7000")

    def test_blocks_insufficient_cash(self, paper_trader, long_signal):
        """Should raise error if insufficient cash."""
        entry_price = Decimal("50000")
        quantity = Decimal("1.0")  # Would need $50,000, only have $10,000

        with pytest.raises(ValueError, match="Insufficient cash"):
            paper_trader.execute_entry(long_signal, entry_price, quantity)


class TestExecuteExit:
    """Test closing positions."""

    def test_closes_profitable_long(self, paper_trader, long_signal):
        """Should close long position with profit."""
        # Open position
        entry_price = Decimal("50000")
        quantity = Decimal("0.1")
        position = paper_trader.execute_entry(long_signal, entry_price, quantity)

        # Cash after entry: $10,000 - $5,000 = $5,000
        assert paper_trader.get_cash_balance() == Decimal("5000")

        # Close at profit
        exit_price = Decimal("52000")  # +$200 profit
        paper_trader.execute_exit(position, exit_price)

        # Cash: $5,000 + $5,200 (position value) + $200 (P&L) = $10,400
        # Wait, that's double counting. Let me recalculate:
        # Cash: $5,000 + $5,200 (exit value) = $10,200
        # Actually P&L = (52000 - 50000) * 0.1 = $200
        # Cash should be: $5,000 + $5,200 + $200 = $10,400
        # Hmm, there's an issue with the logic. Let me think...
        #
        # Actually:
        # Exit value = 52000 * 0.1 = $5,200
        # P&L = (52000 - 50000) * 0.1 = $200
        # Cash after = $5,000 + $5,200 + $200 = $10,400
        # But that's adding position value AND P&L separately, which double counts.
        #
        # Correct logic:
        # Cash after = $5,000 + $5,200 = $10,200
        # OR: Cash after = $5,000 + $5,000 + $200 = $10,200
        # The second form is: cash + original_value + pnl
        #
        # Looking at the code: new_cash = cash + position_value + pnl
        # position_value = exit_price * quantity = $5,200
        # pnl = $200
        # So: $5,000 + $5,200 + $200 = $10,400 ❌
        #
        # This is wrong! Should be: $5,000 + $5,000 (original) + $200 (profit) = $10,200
        # Or simpler: $5,000 + $5,200 (exit value which includes profit) = $10,200
        #
        # The bug is we're adding position_value (at exit) PLUS pnl (which is already in exit value)
        # Fix: new_cash = cash + (entry_price * quantity) + pnl
        # OR: new_cash = cash + (exit_price * quantity)

        assert paper_trader.get_cash_balance() == Decimal("10200")
        assert paper_trader.get_account_value() == Decimal("10200")

    def test_closes_losing_long(self, paper_trader, long_signal):
        """Should close long position with loss."""
        # Open position
        entry_price = Decimal("50000")
        quantity = Decimal("0.1")
        position = paper_trader.execute_entry(long_signal, entry_price, quantity)

        # Close at loss
        exit_price = Decimal("49000")  # -$100 loss
        paper_trader.execute_exit(position, exit_price)

        # Cash: $5,000 + $4,900 = $9,900
        assert paper_trader.get_cash_balance() == Decimal("9900")
        assert paper_trader.get_account_value() == Decimal("9900")

    def test_closes_profitable_short(self, paper_trader, short_signal):
        """Should close short position with profit."""
        # Open short at $3,000
        entry_price = Decimal("3000")
        quantity = Decimal("1.0")
        position = paper_trader.execute_entry(short_signal, entry_price, quantity)

        # Cash: $10,000 - $3,000 = $7,000
        assert paper_trader.get_cash_balance() == Decimal("7000")

        # Close short at $2,500 (price dropped, profit for short)
        exit_price = Decimal("2500")  # +$500 profit
        paper_trader.execute_exit(position, exit_price)

        # Cash: $7,000 + $2,500 + $500 = $10,000
        # Wait same issue. Should be: $7,000 + $3,000 + $500 = $10,500
        # OR: $7,000 + $2,500 (exit value) = $9,500 ❌
        #
        # For SHORT:
        # P&L = (entry - exit) * quantity = (3000 - 2500) * 1 = $500
        # Exit value = 2500 * 1 = $2,500
        # Cash should be: $7,000 + original_collateral ($3,000) + profit ($500) = $10,500
        #
        # Current code: cash + position_value + pnl = $7,000 + $2,500 + $500 = $10,000 ❌

        assert paper_trader.get_cash_balance() == Decimal("10500")


class TestUpdateEquity:
    """Test equity updates."""

    def test_updates_equity_with_unrealized_pnl(self, paper_trader):
        """Should update equity to cash + unrealized P&L."""
        # Cash is $10,000
        # Add $500 unrealized profit
        paper_trader.update_equity(Decimal("500"))

        assert paper_trader.get_cash_balance() == Decimal("10000")
        assert paper_trader.get_account_value() == Decimal("10500")

    def test_updates_equity_with_unrealized_loss(self, paper_trader):
        """Should update equity with unrealized loss."""
        paper_trader.update_equity(Decimal("-200"))

        assert paper_trader.get_cash_balance() == Decimal("10000")
        assert paper_trader.get_account_value() == Decimal("9800")
