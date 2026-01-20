"""Tests for risk manager."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from src.engine.risk_manager import RiskManager
from src.models.position import Direction, Position, PositionStatus
from src.models.signal import Signal, SignalType


@pytest.fixture
def risk_manager():
    """Create risk manager with default settings."""
    return RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),  # 20%
        stop_loss_pct=Decimal("0.02"),  # 2%
        take_profit_pct=Decimal("0.05"),  # 5%
    )


@pytest.fixture
def strong_signal():
    """Create a strong buy signal."""
    return Signal(
        pair="BTC/USD",
        signal_type=SignalType.ENTRY_LONG,
        strength=Decimal("0.8"),
        strategy_name="test_strategy",
        reasoning="Strong bullish momentum",
        timestamp=datetime.now(timezone.utc),
        indicators={"rsi": 25},
    )


@pytest.fixture
def weak_signal():
    """Create a weak buy signal."""
    return Signal(
        pair="BTC/USD",
        signal_type=SignalType.ENTRY_LONG,
        strength=Decimal("0.3"),
        strategy_name="test_strategy",
        reasoning="Weak signal",
        timestamp=datetime.now(timezone.utc),
        indicators={"rsi": 45},
    )


@pytest.fixture
def open_position():
    """Create an open long position."""
    return Position(
        id="pos_1",
        pair="BTC/USD",
        direction=Direction.LONG,
        entry_price=Decimal("50000"),
        quantity=Decimal("0.1"),
        entry_time=datetime.now(timezone.utc),
        strategy_name="test_strategy",
        status=PositionStatus.OPEN,
    )


class TestCanOpenPosition:
    """Test can_open_position logic."""

    def test_allows_strong_signal_with_capacity(self, risk_manager, strong_signal):
        """Should allow opening when all conditions met."""
        can_open, reason = risk_manager.can_open_position(
            signal=strong_signal,
            open_positions_count=3,
            has_position_for_pair=False,
        )

        assert can_open is True
        assert "passed" in reason.lower()

    def test_blocks_duplicate_pair(self, risk_manager, strong_signal):
        """Should block if pair already has position."""
        can_open, reason = risk_manager.can_open_position(
            signal=strong_signal,
            open_positions_count=3,
            has_position_for_pair=True,  # Already have position
        )

        assert can_open is False
        assert "already have position" in reason.lower()

    def test_blocks_when_at_max_positions(self, risk_manager, strong_signal):
        """Should block when at max concurrent positions."""
        can_open, reason = risk_manager.can_open_position(
            signal=strong_signal,
            open_positions_count=5,  # At max
            has_position_for_pair=False,
        )

        assert can_open is False
        assert "max positions" in reason.lower()

    def test_blocks_weak_signal(self, risk_manager, weak_signal):
        """Should block signals with strength <= 0.5."""
        can_open, reason = risk_manager.can_open_position(
            signal=weak_signal,
            open_positions_count=3,
            has_position_for_pair=False,
        )

        assert can_open is False
        assert "weak" in reason.lower()


class TestCalculatePositionSize:
    """Test position sizing calculations."""

    def test_calculates_20_percent_of_account(self, risk_manager):
        """Should calculate 20% of account value."""
        account_value = Decimal("10000")
        entry_price = Decimal("50000")

        # 20% of $10,000 = $2,000
        # $2,000 / $50,000 = 0.04 BTC
        quantity = risk_manager.calculate_position_size(account_value, entry_price)

        expected = Decimal("0.04")
        assert quantity == expected

    def test_adjusts_for_different_prices(self, risk_manager):
        """Should adjust quantity based on entry price."""
        account_value = Decimal("10000")
        entry_price = Decimal("100000")  # Higher price

        # 20% of $10,000 = $2,000
        # $2,000 / $100,000 = 0.02 BTC
        quantity = risk_manager.calculate_position_size(account_value, entry_price)

        expected = Decimal("0.02")
        assert quantity == expected


class TestShouldClosePosition:
    """Test exit condition checks."""

    def test_triggers_stop_loss(self, risk_manager, open_position):
        """Should trigger stop loss at -2% or worse."""
        # Entry: $50,000, Quantity: 0.1
        # -2% = $49,000
        current_price = Decimal("49000")

        should_close, reason = risk_manager.should_close_position(
            open_position, current_price
        )

        assert should_close is True
        assert "stop loss" in reason.lower()

    def test_triggers_take_profit(self, risk_manager, open_position):
        """Should trigger take profit at +5% or better."""
        # Entry: $50,000, Quantity: 0.1
        # +5% = $52,500
        current_price = Decimal("52500")

        should_close, reason = risk_manager.should_close_position(
            open_position, current_price
        )

        assert should_close is True
        assert "take profit" in reason.lower()

    def test_holds_when_in_range(self, risk_manager, open_position):
        """Should hold position when between stop/take profit."""
        # Entry: $50,000
        # Price within range
        current_price = Decimal("51000")  # +2% (within range)

        should_close, reason = risk_manager.should_close_position(
            open_position, current_price
        )

        assert should_close is False
        assert "no exit" in reason.lower()

    def test_stop_loss_for_short_position(self, risk_manager):
        """Should trigger stop loss for short positions correctly."""
        short_position = Position(
            id="pos_short",
            pair="BTC/USD",
            direction=Direction.SHORT,
            entry_price=Decimal("50000"),
            quantity=Decimal("0.1"),
            entry_time=datetime.now(timezone.utc),
            strategy_name="test_strategy",
            status=PositionStatus.OPEN,
        )

        # Short entry: $50,000
        # -2% for SHORT means price went UP by 2%
        # $50,000 * 1.02 = $51,000
        current_price = Decimal("51000")

        should_close, reason = risk_manager.should_close_position(
            short_position, current_price
        )

        assert should_close is True
        assert "stop loss" in reason.lower()


class TestTotalExposure:
    """Test exposure calculations."""

    def test_calculates_exposure_percentage(self, risk_manager):
        """Should calculate exposure as % of account."""
        total_exposure = Decimal("5000")
        account_value = Decimal("10000")

        exposure_pct = risk_manager.get_total_exposure_pct(
            total_exposure, account_value
        )

        assert exposure_pct == Decimal("0.5")  # 50%

    def test_handles_zero_account_value(self, risk_manager):
        """Should return 0% for zero account value."""
        exposure_pct = risk_manager.get_total_exposure_pct(
            Decimal("1000"), Decimal("0")
        )

        assert exposure_pct == Decimal("0")
