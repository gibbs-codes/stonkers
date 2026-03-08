"""EMA Crossover Strategy.

Logic:
- LONG: Fast EMA crosses ABOVE Slow EMA
- SHORT: Fast EMA crosses BELOW Slow EMA

Classic trend-following strategy.
"""
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class EmaCrossoverStrategy(Strategy):
    """EMA crossover trend-following strategy."""

    def __init__(
        self,
        fast_period: int = 9,
        slow_period: int = 21,
        trend_filter_period: int = 200,
        trend_filter_buffer: float = 0.002,
        min_signal_strength: Decimal = Decimal("0.55"),
    ):
        """Initialize EMA Crossover strategy.

        Args:
            fast_period: Fast EMA period (default 9)
            slow_period: Slow EMA period (default 21)
            trend_filter_period: Higher-timeframe EMA to filter trades (default 200)
            trend_filter_buffer: % buffer around trend EMA to avoid chop (default 0.2%)
            min_signal_strength: Minimum strength for signal (0.0-1.0)
        """
        super().__init__(name="EMA_CROSS")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.trend_filter_period = trend_filter_period
        self.trend_filter_buffer = trend_filter_buffer
        self.min_signal_strength = (
            min_signal_strength
            if isinstance(min_signal_strength, Decimal)
            else Decimal(str(min_signal_strength))
        )

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for EMA crossover signals.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if crossover detected, None otherwise
        """
        # Skip if market is ranging (trend following underperforms)
        if self.regime and self.regime.status == "ranging":
            return None

        # Need enough candles for slow EMA + 2 periods for crossover detection
        min_required = max(self.slow_period, self.trend_filter_period) + 2
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Calculate both EMAs
        df['fast_ema'] = df['close'].ewm(span=self.fast_period, adjust=False).mean()
        df['slow_ema'] = df['close'].ewm(span=self.slow_period, adjust=False).mean()
        df['trend_ema'] = df['close'].ewm(span=self.trend_filter_period, adjust=False).mean()

        # Get current and previous values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_fast = current['fast_ema']
        current_slow = current['slow_ema']
        previous_fast = previous['fast_ema']
        previous_slow = previous['slow_ema']
        trend_ema = current['trend_ema']
        current_price = current['close']

        # Trend filter: only take longs above higher-timeframe EMA and shorts below
        long_trend_ok = current_price > trend_ema * (1 + self.trend_filter_buffer)
        short_trend_ok = current_price < trend_ema * (1 - self.trend_filter_buffer)

        # LONG: Fast crosses above slow (golden cross)
        if long_trend_ok and previous_fast <= previous_slow and current_fast > current_slow:
            # Signal strength based on how far apart EMAs are after cross
            separation_pct = abs((current_fast - current_slow) / current_slow)
            # Larger separation = stronger signal (more conviction)
            strength = min(Decimal("1.0"), self.min_signal_strength + Decimal(str(separation_pct * 10)))

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Fast EMA ({self.fast_period}) crossed above Slow EMA ({self.slow_period}). Fast: ${current_fast:.2f}, Slow: ${current_slow:.2f}",
                timestamp=candles[-1].timestamp,
                indicators={
                    'fast_ema': float(current_fast),
                    'slow_ema': float(current_slow),
                    'trend_ema': float(trend_ema),
                    'separation_pct': float(separation_pct),
                }
            )

        # SHORT: Fast crosses below slow (death cross)
        if short_trend_ok and previous_fast >= previous_slow and current_fast < current_slow:
            separation_pct = abs((current_fast - current_slow) / current_slow)
            strength = min(Decimal("1.0"), self.min_signal_strength + Decimal(str(separation_pct * 10)))

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Fast EMA ({self.fast_period}) crossed below Slow EMA ({self.slow_period}). Fast: ${current_fast:.2f}, Slow: ${current_slow:.2f}",
                timestamp=candles[-1].timestamp,
                indicators={
                    'fast_ema': float(current_fast),
                    'slow_ema': float(current_slow),
                    'trend_ema': float(trend_ema),
                    'separation_pct': float(separation_pct),
                }
            )

        return None

    def diagnostics(self, candles: List[Candle]) -> dict:
        """Return current indicator values and condition statuses for debugging."""
        min_required = max(self.slow_period, self.trend_filter_period) + 2
        if not candles or len(candles) < min_required:
            return {"status": f"need {min_required} candles, have {len(candles) if candles else 0}"}

        df = self._candles_to_df(candles)
        df['fast_ema'] = df['close'].ewm(span=self.fast_period, adjust=False).mean()
        df['slow_ema'] = df['close'].ewm(span=self.slow_period, adjust=False).mean()
        df['trend_ema'] = df['close'].ewm(span=self.trend_filter_period, adjust=False).mean()

        current = df.iloc[-1]
        previous = df.iloc[-2]
        price = current['close']
        fast = current['fast_ema']
        slow = current['slow_ema']
        prev_fast = previous['fast_ema']
        prev_slow = previous['slow_ema']
        trend = current['trend_ema']

        golden_cross = prev_fast <= prev_slow and fast > slow
        death_cross = prev_fast >= prev_slow and fast < slow
        long_trend = price > trend * (1 + self.trend_filter_buffer)
        short_trend = price < trend * (1 - self.trend_filter_buffer)

        return {
            "price": f"${price:.2f}",
            "fast_ema": f"${fast:.2f}",
            "slow_ema": f"${slow:.2f}",
            "ema_gap": f"${fast - slow:.2f} ({'fast>slow' if fast > slow else 'fast<slow'})",
            "trend_ema": f"${trend:.2f}",
            "golden_cross": f"{'PASS' if golden_cross else 'FAIL'} (fast must cross above slow)",
            "death_cross": f"{'PASS' if death_cross else 'FAIL'} (fast must cross below slow)",
            "long_trend": f"{'PASS' if long_trend else 'FAIL'} (price must be >{self.trend_filter_buffer:.1%} above trend)",
            "short_trend": f"{'PASS' if short_trend else 'FAIL'} (price must be >{self.trend_filter_buffer:.1%} below trend)",
        }

    def _candles_to_df(self, candles: List[Candle]) -> pd.DataFrame:
        """Convert candles to pandas DataFrame.

        Args:
            candles: List of candles

        Returns:
            DataFrame with OHLCV data
        """
        return pd.DataFrame([
            {
                'close': float(c.close),
            }
            for c in candles
        ])
