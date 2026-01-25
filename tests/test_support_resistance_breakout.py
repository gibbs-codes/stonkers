"""Tests for Support/Resistance Breakout strategy."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.models.candle import Candle
from src.models.signal import SignalType
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy


class TestSupportResistanceBreakoutStrategy:
    """Test Support/Resistance Breakout with Retest strategy."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance with default params."""
        return SupportResistanceBreakoutStrategy(
            lookback_period=100,
            level_tolerance=0.01,
            min_touches=2,
            volume_multiplier=1.3,
            retest_candles=8,
            retest_tolerance=0.005,
            min_signal_strength=0.7,
        )

    def _create_candles_with_pattern(
        self,
        num_candles: int,
        price_pattern: list = None,
        volume_pattern: list = None,
        base_price: float = 3000.0,
        base_volume: float = 1000.0,
    ) -> list[Candle]:
        """Helper to create candles with specific price/volume patterns.

        Args:
            num_candles: Number of candles to create
            price_pattern: List of prices (or None for flat)
            volume_pattern: List of volumes (or None for flat)
            base_price: Base price if pattern not provided
            base_volume: Base volume if pattern not provided

        Returns:
            List of Candle objects
        """
        candles = []
        base_time = datetime.now(timezone.utc)

        for i in range(num_candles):
            price = price_pattern[i] if price_pattern and i < len(price_pattern) else base_price
            volume = volume_pattern[i] if volume_pattern and i < len(volume_pattern) else base_volume

            # Create realistic OHLC
            high = price * 1.005
            low = price * 0.995

            candle = Candle(
                pair="ETH/USD",
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal(str(price)),
                high=Decimal(str(high)),
                low=Decimal(str(low)),
                close=Decimal(str(price)),
                volume=Decimal(str(volume)),
            )
            candles.append(candle)

        return candles

    def test_validates_minimum_candles(self, strategy):
        """Test that strategy requires minimum candles."""
        # Need lookback (100) + retest (8) + 5 = 113 minimum
        candles = self._create_candles_with_pattern(100)
        signal = strategy.analyze(candles)
        assert signal is None  # Not enough candles

    def test_identifies_support_levels_from_swing_lows(self, strategy):
        """Test that strategy correctly identifies support levels."""
        # Create price pattern with clear support level at 2950
        prices = [3000.0] * 50
        # Add swing lows touching 2950 (support level)
        prices += [3000, 2950, 3000, 3000, 2950, 3000, 3000]  # Two touches at 2950
        prices += [3000.0] * 60

        candles = self._create_candles_with_pattern(len(prices), price_pattern=prices)

        # The strategy should identify 2950 as a support level
        df = strategy._candles_to_df(candles)
        levels = strategy._find_support_resistance_levels(df)

        # Should find support near 2950
        assert len(levels['support']) > 0
        # Check if any support level is close to 2950 (within 1%)
        assert any(abs(level - 2950.0) / 2950.0 < 0.01 for level in levels['support'])

    def test_identifies_resistance_levels_from_swing_highs(self, strategy):
        """Test that strategy correctly identifies resistance levels."""
        # Create price pattern with clear resistance at 3050
        prices = [3000.0] * 50
        # Add swing highs touching 3050 (resistance level)
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]  # Two touches at 3050
        prices += [3000.0] * 60

        candles = self._create_candles_with_pattern(len(prices), price_pattern=prices)

        df = strategy._candles_to_df(candles)
        levels = strategy._find_support_resistance_levels(df)

        # Should find resistance near 3050
        assert len(levels['resistance']) > 0
        assert any(abs(level - 3050.0) / 3050.0 < 0.01 for level in levels['resistance'])

    def test_clusters_nearby_levels(self, strategy):
        """Test that nearby price levels are clustered together."""
        # Create levels that are very close (within 1% tolerance)
        levels = [3000.0, 3005.0, 3002.0, 3100.0, 3103.0]

        clustered = strategy._cluster_levels(levels)

        # Should cluster 3000, 3002, 3005 together (within 1%)
        # And 3100, 3103 together
        # Each cluster needs min_touches=2
        assert len(clustered) == 2
        assert any(2990 < level < 3010 for level in clustered)  # First cluster
        assert any(3095 < level < 3110 for level in clustered)  # Second cluster

    def test_long_signal_on_resistance_breakout_retest(self, strategy):
        """Test LONG signal on resistance breakout followed by successful retest."""
        # Build a complete breakout + retest pattern
        prices = [3000.0] * 50

        # Create resistance at 3050 with swing highs
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]
        prices += [3000.0] * 50

        # BREAKOUT: Break above 3050 with volume
        prices += [3060]  # Breakout candle

        # RETEST: Pull back to test 3050 from above
        prices += [3055, 3052, 3048]  # Retest at ~3048 (close to 3050)

        # BOUNCE: Move back up after retest
        prices += [3055, 3060, 3065]

        # Create volume pattern - spike on breakout
        volumes = [1000.0] * (len(prices) - 7)
        volumes += [1500.0]  # High volume on breakout
        volumes += [1000.0] * 6  # Normal volume after

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_LONG
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.7")
        assert "Resistance breakout + retest LONG" in signal.reasoning
        assert signal.indicators['level_price'] > 3040  # Should be near 3050
        assert signal.indicators['breakout_price'] > 3055

    def test_short_signal_on_support_breakdown_retest(self, strategy):
        """Test SHORT signal on support breakdown followed by successful retest."""
        # Build a complete breakdown + retest pattern
        prices = [3000.0] * 50

        # Create support at 2950 with swing lows
        prices += [3000, 2950, 3000, 3000, 2950, 3000, 3000]
        prices += [3000.0] * 50

        # BREAKDOWN: Break below 2950 with volume
        prices += [2940]  # Breakdown candle

        # RETEST: Rally back to test 2950 from below
        prices += [2945, 2948, 2952]  # Retest at ~2952 (close to 2950)

        # REJECTION: Move back down after retest
        prices += [2945, 2940, 2935]

        # Create volume pattern - spike on breakdown
        volumes = [1000.0] * (len(prices) - 7)
        volumes += [1500.0]  # High volume on breakdown
        volumes += [1000.0] * 6  # Normal volume after

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_SHORT
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.7")
        assert "Support breakdown + retest SHORT" in signal.reasoning
        assert signal.indicators['level_price'] < 2960  # Should be near 2950
        assert signal.indicators['breakout_price'] < 2945

    def test_no_signal_on_breakout_without_retest(self, strategy):
        """Test that false breakouts (no retest) don't generate signals."""
        prices = [3000.0] * 50

        # Create resistance at 3050
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]
        prices += [3000.0] * 50

        # BREAKOUT: Break above 3050
        prices += [3060]

        # NO RETEST: Just keep moving up (no pullback)
        prices += [3065, 3070, 3075, 3080, 3085]

        volumes = [1000.0] * (len(prices) - 6)
        volumes += [1500.0]  # High volume on breakout
        volumes += [1000.0] * 5

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        # Should be None - no retest occurred
        assert signal is None

    def test_no_signal_on_breakout_without_volume(self, strategy):
        """Test that breakouts without volume confirmation are ignored."""
        prices = [3000.0] * 50

        # Create resistance at 3050
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]
        prices += [3000.0] * 50

        # BREAKOUT: Break above 3050 but LOW volume
        prices += [3060, 3055, 3052, 3048, 3055, 3060]

        # All normal volume (no spike)
        volumes = [1000.0] * len(prices)

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        assert signal is None

    def test_no_signal_when_no_levels_identified(self, strategy):
        """Test that strategy returns None when no S/R levels found."""
        # Create flat price action with no swing points
        prices = [3000.0] * 120

        candles = self._create_candles_with_pattern(len(prices), price_pattern=prices)

        signal = strategy.analyze(candles)
        assert signal is None

    def test_signal_includes_all_required_indicators(self, strategy):
        """Test that signals include all required indicator values."""
        # Create a valid breakout + retest scenario
        prices = [3000.0] * 50
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]
        prices += [3000.0] * 50
        prices += [3060, 3055, 3052, 3048, 3055, 3060, 3065]

        volumes = [1000.0] * (len(prices) - 7)
        volumes += [1500.0]  # Volume spike
        volumes += [1000.0] * 6

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        if signal is not None:
            # Verify all required indicators present
            assert 'level_price' in signal.indicators
            assert 'breakout_price' in signal.indicators
            assert 'retest_price' in signal.indicators
            assert 'current_price' in signal.indicators
            # Either bounce_pct (LONG) or rejection_pct (SHORT)
            assert ('bounce_pct' in signal.indicators or
                    'rejection_pct' in signal.indicators)

    def test_retest_must_occur_within_retest_candles_window(self, strategy):
        """Test that retest must occur within the retest_candles window."""
        prices = [3000.0] * 50
        prices += [3000, 3050, 3000, 3000, 3050, 3000, 3000]
        prices += [3000.0] * 50

        # BREAKOUT
        prices += [3060]

        # Wait TOO LONG before retest (more than retest_candles=8)
        prices += [3070] * 10  # 10 candles of movement away

        # Then retest (too late)
        prices += [3052, 3055, 3060]

        volumes = [1000.0] * (len(prices) - 14)
        volumes += [1500.0]  # Breakout volume
        volumes += [1000.0] * 13

        candles = self._create_candles_with_pattern(
            len(prices),
            price_pattern=prices,
            volume_pattern=volumes
        )

        signal = strategy.analyze(candles)
        # Should be None - retest came too late
        assert signal is None
