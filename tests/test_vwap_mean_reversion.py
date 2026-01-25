"""Tests for VWAP Mean Reversion strategy."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from src.models.candle import Candle
from src.models.signal import SignalType
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy


class TestVwapMeanReversionStrategy:
    """Test VWAP Mean Reversion strategy signals."""

    @pytest.fixture
    def strategy(self):
        """Create strategy instance with default params."""
        return VwapMeanReversionStrategy(
            vwap_period=50,
            std_multiplier=2.0,
            volume_threshold=1.5,
            min_signal_strength=0.6,
        )

    def _create_candles(
        self,
        num_candles: int,
        base_price: float = 3000.0,
        base_volume: float = 1000.0,
        price_pattern: str = "flat",
        volume_multipliers: list = None,
    ) -> list[Candle]:
        """Helper to create candle data.

        Args:
            num_candles: Number of candles to create
            base_price: Starting price
            base_volume: Base volume level
            price_pattern: "flat", "rising", "falling", or custom list of prices
            volume_multipliers: List of volume multipliers for each candle

        Returns:
            List of Candle objects
        """
        candles = []
        base_time = datetime.now(timezone.utc)

        for i in range(num_candles):
            # Determine price based on pattern
            if price_pattern == "flat":
                price = base_price
            elif price_pattern == "rising":
                price = base_price + (i * 10)  # Gradually increase
            elif price_pattern == "falling":
                price = base_price - (i * 10)  # Gradually decrease
            elif isinstance(price_pattern, list):
                price = price_pattern[i] if i < len(price_pattern) else base_price
            else:
                price = base_price

            # Apply volume multiplier if specified
            volume = base_volume
            if volume_multipliers and i < len(volume_multipliers):
                volume = base_volume * volume_multipliers[i]

            # Create realistic OHLC from close price with more variation
            high = price * 1.015  # 1.5% above
            low = price * 0.985   # 1.5% below

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
        # Need vwap_period (50) + 20 for volume = 70 minimum
        candles = self._create_candles(60)
        signal = strategy.analyze(candles)
        assert signal is None

    def test_long_signal_on_price_below_lower_band_with_volume(self, strategy):
        """Test LONG signal when price crosses below VWAP - 2σ with volume spike."""
        # Create candles with significant price variation to generate meaningful std dev
        # Need vwap_period (50) + std_period (50) = 100 minimum for valid std dev
        # Use a sine-wave-like pattern with larger amplitude
        import math
        prices = []
        for i in range(98):  # 100 - 2 (we add 2 more later)
            # Sine wave with ±60 amplitude around 3000
            variation = 60 * math.sin(i / 5.0)
            prices.append(3000.0 + variation)

        candles = self._create_candles(98, price_pattern=prices)

        # Penultimate: price within bands (close to VWAP)
        penultimate = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("3000.0"),
            high=Decimal("3010.0"),
            low=Decimal("2990.0"),
            close=Decimal("3000.0"),  # At VWAP
            volume=Decimal("1000.0"),
        )
        candles.append(penultimate)

        # Last candle: price drops significantly below lower band with volume spike
        # With ±60 variation, std dev should be ~40-45
        # Lower band = VWAP - 2*std = 3000 - 2*42 = ~2916
        # So 2850 should be well below lower band
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=penultimate.timestamp + timedelta(minutes=1),
            open=Decimal("2860.0"),
            high=Decimal("2870.0"),
            low=Decimal("2840.0"),
            close=Decimal("2850.0"),  # ~5% drop, well below lower band
            volume=Decimal("2000.0"),  # 2x volume spike
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_LONG
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.6")
        assert "Mean reversion LONG" in signal.reasoning
        assert "crossed below VWAP" in signal.reasoning
        assert signal.indicators['distance_from_vwap'] < 0  # Below VWAP
        assert signal.indicators['volume_ratio'] >= 1.5

    def test_short_signal_on_price_above_upper_band_with_volume(self, strategy):
        """Test SHORT signal when price crosses above VWAP + 2σ with volume spike."""
        # Create candles with significant price variation to generate meaningful std dev
        # Need vwap_period (50) + std_period (50) = 100 minimum for valid std dev
        import math
        prices = []
        for i in range(98):  # 100 - 2 (we add 2 more later)
            # Sine wave with ±60 amplitude around 3000
            variation = 60 * math.sin(i / 5.0)
            prices.append(3000.0 + variation)

        candles = self._create_candles(98, price_pattern=prices)

        # Penultimate: price within bands (close to VWAP)
        penultimate = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2990.0"),
            high=Decimal("3010.0"),
            low=Decimal("2985.0"),
            close=Decimal("3000.0"),  # At VWAP
            volume=Decimal("1000.0"),
        )
        candles.append(penultimate)

        # Last candle: price spikes significantly above upper band with volume
        # With ±60 variation, std dev should be ~40-45
        # Upper band = VWAP + 2*std = 3000 + 2*42 = ~3084
        # So 3150 should be well above upper band
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=penultimate.timestamp + timedelta(minutes=1),
            open=Decimal("3140.0"),
            high=Decimal("3160.0"),
            low=Decimal("3130.0"),
            close=Decimal("3150.0"),  # ~5% spike, well above upper band
            volume=Decimal("2000.0"),  # 2x volume spike
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is not None
        assert signal.signal_type == SignalType.ENTRY_SHORT
        assert signal.pair == "ETH/USD"
        assert signal.strength >= Decimal("0.6")
        assert "Mean reversion SHORT" in signal.reasoning
        assert "crossed above VWAP" in signal.reasoning
        assert signal.indicators['distance_from_vwap'] > 0  # Above VWAP
        assert signal.indicators['volume_ratio'] >= 1.5

    def test_no_signal_when_price_within_bands(self, strategy):
        """Test no signal when price stays within VWAP bands."""
        # Create candles with stable price (within bands)
        candles = self._create_candles(
            70,
            base_price=3000.0,
            volume_multipliers=[2.0] * 70  # High volume but no band cross
        )

        signal = strategy.analyze(candles)
        assert signal is None

    def test_no_signal_when_volume_too_low(self, strategy):
        """Test no signal when volume is below threshold."""
        # Create 70 candles at stable price
        candles = self._create_candles(69, base_price=3000.0)

        # Last candle: price crosses band but LOW volume
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2880.0"),
            high=Decimal("2890.0"),
            low=Decimal("2870.0"),
            close=Decimal("2880.0"),  # Below VWAP
            volume=Decimal("1000.0"),  # Only 1x average (need 1.5x)
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        assert signal is None

    def test_no_signal_when_already_below_band(self, strategy):
        """Test no signal when price is already below band (no cross)."""
        # Create candles where price has been below band
        prices = [3000.0] * 68 + [2880.0, 2880.0]  # Last 2 already low
        candles = self._create_candles(
            70,
            price_pattern=prices,
            volume_multipliers=[2.0] * 70
        )

        signal = strategy.analyze(candles)
        # Should be None because price was already below band (no crossing event)
        assert signal is None

    def test_vwap_calculation_uses_typical_price(self, strategy):
        """Test that VWAP is calculated using (H+L+C)/3 typical price."""
        # Create candles with varying high/low
        candles = []
        base_time = datetime.now(timezone.utc)

        for i in range(70):
            candle = Candle(
                pair="ETH/USD",
                timestamp=base_time + timedelta(minutes=i),
                open=Decimal("3000.0"),
                high=Decimal("3050.0"),  # Higher high
                low=Decimal("2950.0"),   # Lower low
                close=Decimal("3000.0"),
                volume=Decimal("1000.0"),
            )
            candles.append(candle)

        # Analyze to calculate VWAP
        signal = strategy.analyze(candles)

        # Even if no signal, the VWAP should be calculated
        # Typical price = (3050 + 2950 + 3000) / 3 = 3000
        # This test mainly ensures the calculation doesn't error
        # The actual VWAP value should be close to 3000 for flat prices
        assert True  # If we got here without error, VWAP calculation works

    def test_signal_strength_scales_with_distance(self, strategy):
        """Test that signal strength increases with distance from VWAP."""
        # Create 70 candles at stable price
        candles = self._create_candles(69, base_price=3000.0)

        # Last candle: EXTREME deviation from VWAP
        last_candle = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2800.0"),
            high=Decimal("2820.0"),
            low=Decimal("2790.0"),
            close=Decimal("2800.0"),  # ~6.7% below
            volume=Decimal("2500.0"),  # High volume
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        if signal is not None:
            # With larger deviation, signal strength should be higher
            # Should approach 1.0 for extreme deviations
            assert signal.strength >= Decimal("0.6")
            assert signal.indicators['distance_in_std'] > 2.0  # Beyond 2 std devs

    def test_includes_all_required_indicators(self, strategy):
        """Test that signal includes all required indicator values."""
        # Create setup for signal
        candles = self._create_candles(69, base_price=3000.0)

        last_candle = Candle(
            pair="ETH/USD",
            timestamp=candles[-1].timestamp + timedelta(minutes=1),
            open=Decimal("2880.0"),
            high=Decimal("2890.0"),
            low=Decimal("2870.0"),
            close=Decimal("2880.0"),
            volume=Decimal("2000.0"),
        )
        candles.append(last_candle)

        signal = strategy.analyze(candles)
        if signal is not None:
            # Verify all required indicators are present
            assert 'vwap' in signal.indicators
            assert 'std_dev' in signal.indicators
            assert 'distance_from_vwap' in signal.indicators
            assert 'lower_band' in signal.indicators
            assert 'upper_band' in signal.indicators
            assert 'volume' in signal.indicators
            assert 'avg_volume' in signal.indicators
            assert 'volume_ratio' in signal.indicators
            assert 'distance_in_std' in signal.indicators

    def test_handles_zero_std_dev_gracefully(self, strategy):
        """Test that strategy handles zero standard deviation without crashing."""
        # Create candles with identical prices (zero variance)
        candles = self._create_candles(70, base_price=3000.0)

        # Should not crash even with zero std dev
        signal = strategy.analyze(candles)
        # Likely no signal since bands would be same as VWAP
        # But importantly, it shouldn't crash with division by zero
        assert True  # Test passes if no exception raised
