"""Tests for Momentum Thrust strategy."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.models.candle import Candle
from src.models.signal import SignalType
from src.strategies.momentum_thrust import MomentumThrustStrategy


class TestMomentumThrustStrategy:
    """Test Momentum Thrust strategy signals."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance with default params."""
        return MomentumThrustStrategy(
            roc_period=14,
            entry_threshold=5.0,
            exit_threshold=2.0,
            volume_multiplier=1.5,
            min_signal_strength=0.6,
        )

    def _create_candles(
        self,
        num_candles: int,
        base_price: float = 3000.0,
        base_volume: float = 1000.0,
        price_changes: list = None,
        volume_multipliers: list = None,
    ) -> list[Candle]:
        """Helper to create candle data.

        Args:
            num_candles: Number of candles to create
            base_price: Starting price
            base_volume: Base volume level
            price_changes: List of price changes (percentage) for each candle
            volume_multipliers: List of volume multipliers for each candle

        Returns:
            List of Candle objects
        """
        candles = []
        current_price = base_price
        base_time = datetime.now(timezone.utc)

        for i in range(num_candles):
            # Apply price change if specified
            if price_changes and i < len(price_changes):
                current_price = current_price * (1 + price_changes[i] / 100)

            # Apply volume multiplier if specified
            volume = base_volume
            if volume_multipliers and i < len(volume_multipliers):
                volume = base_volume * volume_multipliers[i]

            candle = Candle(
                pair="ETH/USD",
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal(str(current_price)),
                high=Decimal(str(current_price * 1.01)),
                low=Decimal(str(current_price * 0.99)),
                close=Decimal(str(current_price)),
                volume=Decimal(str(volume)),
            )
            candles.append(candle)

        return candles

    def test_validates_minimum_candles(self, strategy):
        """Test that strategy requires minimum candles."""
        # Need roc_period (14) + 20 for volume + 5 buffer = 39 minimum
        candles = self._create_candles(30)
        signal = strategy.analyze(candles)
        assert signal is None

    def test_long_signal_on_roc_cross_above_threshold_with_volume(self, strategy):
        """Test LONG signal when ROC crosses above +5% with volume spike."""
        # Create 38 candles with flat price at 3000
        candles = self._create_candles(38, base_price=3000.0)

        # Index 38 will be penultimate, looking back 14 to index 24
        # Index 39 will be last, looking back 14 to index 25
        # Set indices 24-25 to lower price
        candles[24] = Candle(
            pair="ETH/USD",
            timestamp=candles[24].timestamp,
            open=Decimal("2850.0"),
            high=Decimal("2900.0"),
            low=Decimal("2850.0"),
            close=Decimal("2850.0"),
            volume=Decimal("1000.0"),
        )
        candles[25] = Candle(
            pair="ETH/USD",
            timestamp=candles[25].timestamp,
            open=Decimal("2850.0"),
            high=Decimal("2900.0"),
            low=Decimal("2850.0"),
            close=Decimal("2850.0"),
            volume=Decimal("1000.0"),
        )

        # Second-to-last candle (index 38): ROC from 2850 to 2990 = 4.9% (below 5%)
        penultimate = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2990.0"),
            high=Decimal("3000.0"),
            low=Decimal("2980.0"),
            close=Decimal("2990.0"),
            volume=Decimal("1000.0"),
        )
        candles.append(penultimate)

        # Last candle (index 39): ROC from 2850 to 3000 = 5.26% (above 5%)
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=penultimate.timestamp + timedelta(minutes=1),
            open=Decimal("3000.0"),
            high=Decimal("3030.0"),
            low=Decimal("2990.0"),
            close=Decimal("3000.0"),
            volume=Decimal("2000.0"),  # 2x average volume
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_LONG
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.6")
        assert "ROC crossed above" in signal.reasoning
        assert "volume spike" in signal.reasoning
        assert signal.indicators['roc'] > 5.0
        assert signal.indicators['volume_ratio'] >= 1.5

    def test_short_signal_on_roc_cross_below_threshold_with_volume(self, strategy):
        """Test SHORT signal when ROC crosses below -5% with volume spike."""
        # Create 38 candles with flat price at 3000
        candles = self._create_candles(38, base_price=3000.0)

        # Set indices 24-25 to higher price for negative ROC
        candles[24] = Candle(
            pair="ETH/USD",
            timestamp=candles[24].timestamp,
            open=Decimal("3160.0"),
            high=Decimal("3200.0"),
            low=Decimal("3150.0"),
            close=Decimal("3160.0"),
            volume=Decimal("1000.0"),
        )
        candles[25] = Candle(
            pair="ETH/USD",
            timestamp=candles[25].timestamp,
            open=Decimal("3160.0"),
            high=Decimal("3200.0"),
            low=Decimal("3150.0"),
            close=Decimal("3160.0"),
            volume=Decimal("1000.0"),
        )

        # Second-to-last candle: ROC from 3160 to 3010 = -4.75% (above -5%)
        penultimate = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("3010.0"),
            high=Decimal("3020.0"),
            low=Decimal("3000.0"),
            close=Decimal("3010.0"),
            volume=Decimal("1000.0"),
        )
        candles.append(penultimate)

        # Last candle: ROC from 3160 to 3000 = -5.06% (below -5%)
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=penultimate.timestamp + timedelta(minutes=1),
            open=Decimal("3000.0"),
            high=Decimal("3030.0"),
            low=Decimal("2990.0"),
            close=Decimal("3000.0"),
            volume=Decimal("2000.0"),  # 2x average volume
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_SHORT
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.6")
        assert "ROC crossed below" in signal.reasoning
        assert "volume spike" in signal.reasoning
        assert signal.indicators['roc'] < -5.0
        assert signal.indicators['volume_ratio'] >= 1.5

    def test_no_signal_when_roc_below_threshold(self, strategy):
        """Test no signal when ROC is below entry threshold."""
        # Create candles with small price movement (< 5% ROC)
        price_changes = [0.5] * 40  # Small 0.5% changes
        candles = self._create_candles(
            40,
            price_changes=price_changes,
            volume_multipliers=[2.0] * 40  # High volume but low ROC
        )

        signal = strategy.analyze(candles)
        assert signal is None

    def test_no_signal_when_volume_too_low(self, strategy):
        """Test no signal when volume is below multiplier threshold."""
        # Create 40 candles
        candles = self._create_candles(38, base_price=3000.0)

        # Set candle 14 periods ago lower
        candles[23] = Candle(
            pair="ETH/USD",
            timestamp=candles[23].timestamp,
            open=Decimal("2850.0"),
            high=Decimal("2900.0"),
            low=Decimal("2850.0"),
            close=Decimal("2850.0"),
            volume=Decimal("1000.0"),
        )

        # Last candle: high ROC but LOW volume
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("3000.0"),
            high=Decimal("3030.0"),
            low=Decimal("2990.0"),
            close=Decimal("3000.0"),
            volume=Decimal("1000.0"),  # Only 1x average (need 1.5x)
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is None

    def test_no_signal_when_roc_already_above_threshold(self, strategy):
        """Test no signal when ROC is already above threshold (no cross)."""
        # Create candles where ROC is consistently high (no crossing event)
        candles = self._create_candles(38, base_price=3000.0)

        # Both recent candles have high ROC (already above threshold)
        for i in [22, 23]:
            candles[i] = Candle(
                pair="ETH/USD",
                timestamp=candles[i].timestamp,
                open=Decimal("2800.0"),
                high=Decimal("2850.0"),
                low=Decimal("2800.0"),
                close=Decimal("2800.0"),
                volume=Decimal("1000.0"),
            )

        # Last two candles maintain high price
        for offset in [0, 1]:
            last_candle = Candle(
                pair="ETH/USD",
                timestamp=candles[-1].timestamp + timedelta(minutes=offset + 1),
                open=Decimal("3000.0"),
                high=Decimal("3030.0"),
                low=Decimal("2990.0"),
                close=Decimal("3000.0"),
                volume=Decimal("2000.0"),
            )
            candles.append(last_candle)

        signal = strategy.analyze(candles)
        # Should be None because ROC was already above threshold (no cross)
        assert signal is None

    def test_signal_strength_scales_with_roc_magnitude(self, strategy):
        """Test that signal strength increases with ROC magnitude."""
        # Create 38 candles with flat price at 3000
        candles = self._create_candles(38, base_price=3000.0)

        # Set indices 24-25 to very low price for extreme ROC
        candles[24] = Candle(
            pair="ETH/USD",
            timestamp=candles[24].timestamp,
            open=Decimal("2700.0"),
            high=Decimal("2750.0"),
            low=Decimal("2700.0"),
            close=Decimal("2700.0"),
            volume=Decimal("1000.0"),
        )
        candles[25] = Candle(
            pair="ETH/USD",
            timestamp=candles[25].timestamp,
            open=Decimal("2700.0"),
            high=Decimal("2750.0"),
            low=Decimal("2700.0"),
            close=Decimal("2700.0"),
            volume=Decimal("1000.0"),
        )

        # Second-to-last candle: ROC from 2700 to 2830 = 4.8% (below 5%)
        penultimate = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2830.0"),
            high=Decimal("2840.0"),
            low=Decimal("2820.0"),
            close=Decimal("2830.0"),
            volume=Decimal("1000.0"),
        )
        candles.append(penultimate)

        # Last candle: ROC from 2700 to 3000 = 11.1% (well above 5%)
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=penultimate.timestamp + timedelta(minutes=1),
            open=Decimal("3000.0"),
            high=Decimal("3030.0"),
            low=Decimal("2990.0"),
            close=Decimal("3000.0"),
            volume=Decimal("2500.0"),
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is not None
        # With 11% ROC vs 5% threshold, strength should be higher
        # Strength = min(1.0, ROC / (threshold * 2)) = min(1.0, 11 / 10) = 1.0
        assert signal.strength >= Decimal("0.9")  # Should be very strong
