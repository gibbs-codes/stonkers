"""Tests for data models."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal

from src.models.candle import Candle
from src.models.position import Position, PositionStatus, Direction
from src.models.signal import Signal, SignalType


class TestCandle:
    """Test Candle model validation."""

    def test_valid_candle(self):
        """Test creating a valid candle."""
        candle = Candle(
            pair="BTC/USD",
            timestamp=datetime.now(timezone.utc),
            open=Decimal("50000"),
            high=Decimal("51000"),
            low=Decimal("49000"),
            close=Decimal("50500"),
            volume=Decimal("100")
        )

        assert candle.pair == "BTC/USD"
        assert candle.open == Decimal("50000")

    def test_requires_timezone_aware_timestamp(self):
        """Test that naive datetime is rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            Candle(
                pair="BTC/USD",
                timestamp=datetime.now(),  # Naive!
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100")
            )

    def test_validates_high_not_less_than_low(self):
        """Test that high >= low is enforced."""
        with pytest.raises(ValueError, match="High.*less than low"):
            Candle(
                pair="BTC/USD",
                timestamp=datetime.now(timezone.utc),
                open=Decimal("50000"),
                high=Decimal("48000"),  # Less than low!
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100")
            )

    def test_validates_high_greater_than_open_close(self):
        """Test that high is highest price."""
        with pytest.raises(ValueError, match="High.*must be"):
            Candle(
                pair="BTC/USD",
                timestamp=datetime.now(timezone.utc),
                open=Decimal("51000"),  # Higher than high!
                high=Decimal("50000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100")
            )

    def test_validates_positive_prices(self):
        """Test that negative prices are rejected."""
        with pytest.raises(ValueError, match="must be positive"):
            Candle(
                pair="BTC/USD",
                timestamp=datetime.now(timezone.utc),
                open=Decimal("-50000"),  # Negative!
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100")
            )

    def test_validates_pair_format(self):
        """Test that pair must contain /."""
        with pytest.raises(ValueError, match="BASE/QUOTE"):
            Candle(
                pair="BTCUSD",  # Missing slash!
                timestamp=datetime.now(timezone.utc),
                open=Decimal("50000"),
                high=Decimal("51000"),
                low=Decimal("49000"),
                close=Decimal("50500"),
                volume=Decimal("100")
            )


class TestPosition:
    """Test Position model and lifecycle."""

    def test_open_position_creation(self):
        """Test creating a valid open position."""
        pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy",
            status=PositionStatus.OPEN
        )

        assert pos.status == PositionStatus.OPEN
        assert pos.exit_price is None
        assert pos.exit_time is None

    def test_requires_timezone_aware_times(self):
        """Test that naive datetimes are rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            Position(
                id="test-1",
                pair="BTC/USD",
                direction=Direction.LONG,
                entry_price=Decimal("50000"),
                quantity=Decimal("0.1"),
                entry_time=datetime.now(),  # Naive!
                strategy_name="test_strategy"
            )

    def test_open_position_cannot_have_exit_data(self):
        """Test that open position validation rejects exit data."""
        with pytest.raises(ValueError, match="Open position cannot have"):
            Position(
                id="test-1",
                pair="BTC/USD",
                direction=Direction.LONG,
                entry_price=Decimal("50000"),
                quantity=Decimal("0.1"),
                entry_time=datetime.now(timezone.utc),
                strategy_name="test_strategy",
                status=PositionStatus.OPEN,
                exit_price=Decimal("51000")  # Shouldn't be here!
            )

    def test_closed_position_requires_exit_data(self):
        """Test that closed position must have exit data."""
        with pytest.raises(ValueError, match="Closed position must have"):
            Position(
                id="test-1",
                pair="BTC/USD",
                direction=Direction.LONG,
                entry_price=Decimal("50000"),
                quantity=Decimal("0.1"),
                entry_time=datetime.now(timezone.utc),
                strategy_name="test_strategy",
                status=PositionStatus.CLOSED
                # Missing exit_price and exit_time!
            )

    def test_close_position_transitions_state(self):
        """Test closing a position creates new closed position."""
        open_pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy"
        )

        closed_pos = open_pos.close(Decimal("51000"), "Take profit")

        # Original unchanged (immutable)
        assert open_pos.status == PositionStatus.OPEN
        assert open_pos.exit_price is None

        # New position is closed
        assert closed_pos.status == PositionStatus.CLOSED
        assert closed_pos.exit_price == Decimal("51000")
        assert closed_pos.exit_reason == "Take profit"
        assert closed_pos.exit_time is not None

    def test_cannot_close_already_closed_position(self):
        """Test that closing a closed position raises error."""
        pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy"
        )

        closed = pos.close(Decimal("51000"), "Test")

        with pytest.raises(ValueError, match="already closed"):
            closed.close(Decimal("52000"), "Trying again")

    def test_unrealized_pnl_long(self):
        """Test unrealized P&L calculation for LONG."""
        pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy"
        )

        # Price went up $1000
        pnl = pos.unrealized_pnl(Decimal("51000"))
        assert pnl == Decimal("100")  # 0.1 * 1000

        # Price went down $1000
        pnl = pos.unrealized_pnl(Decimal("49000"))
        assert pnl == Decimal("-100")  # 0.1 * -1000

    def test_unrealized_pnl_short(self):
        """Test unrealized P&L calculation for SHORT."""
        pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.SHORT,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy"
        )

        # Price went down $1000 (good for short)
        pnl = pos.unrealized_pnl(Decimal("49000"))
        assert pnl == Decimal("100")  # 0.1 * 1000

        # Price went up $1000 (bad for short)
        pnl = pos.unrealized_pnl(Decimal("51000"))
        assert pnl == Decimal("-100")  # 0.1 * -1000

    def test_realized_pnl_calculation(self):
        """Test realized P&L after closing."""
        pos = Position(
            id="test-1",
            pair="BTC/USD",
            direction=Direction.LONG,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy"
        )

        closed = pos.close(Decimal("51000"), "Test")
        pnl = closed.realized_pnl()

        assert pnl == Decimal("100")  # 0.1 * (51000 - 50000)


class TestSignal:
    """Test Signal model validation."""

    def test_valid_long_signal(self):
        """Test creating a valid LONG signal."""
        signal = Signal(
            pair="BTC/USD",
            signal_type=SignalType.ENTRY_LONG,
            strength=Decimal("0.75"),
            strategy_name="test_strategy",
            reasoning="RSI oversold and price below EMA",
            timestamp=datetime.now(timezone.utc),
            indicators={"rsi": 28, "ema": 50100}
        )

        assert signal.is_long
        assert not signal.is_short
        assert signal.strength == Decimal("0.75")

    def test_valid_short_signal(self):
        """Test creating a valid SHORT signal."""
        signal = Signal(
            pair="BTC/USD",
            signal_type=SignalType.ENTRY_SHORT,
            strength=Decimal("0.8"),
            strategy_name="test_strategy",
            reasoning="RSI overbought and price above EMA",
            timestamp=datetime.now(timezone.utc),
            indicators={"rsi": 75, "ema": 49900}
        )

        assert signal.is_short
        assert not signal.is_long

    def test_validates_strength_range(self):
        """Test that strength must be 0-1."""
        with pytest.raises(ValueError, match="between 0 and 1"):
            Signal(
                pair="BTC/USD",
                signal_type=SignalType.ENTRY_LONG,
                strength=Decimal("1.5"),  # Too high!
                strategy_name="test_strategy",
                reasoning="Test",
                timestamp=datetime.now(timezone.utc),
                indicators={}
            )

    def test_requires_reasoning(self):
        """Test that reasoning cannot be empty."""
        with pytest.raises(ValueError, match="must include reasoning"):
            Signal(
                pair="BTC/USD",
                signal_type=SignalType.ENTRY_LONG,
                strength=Decimal("0.75"),
                strategy_name="test_strategy",
                reasoning="",  # Empty!
                timestamp=datetime.now(timezone.utc),
                indicators={}
            )

    def test_requires_timezone_aware_timestamp(self):
        """Test that naive datetime is rejected."""
        with pytest.raises(ValueError, match="timezone-aware"):
            Signal(
                pair="BTC/USD",
                signal_type=SignalType.ENTRY_LONG,
                strength=Decimal("0.75"),
                strategy_name="test_strategy",
                reasoning="Test",
                timestamp=datetime.now(),  # Naive!
                indicators={}
            )
