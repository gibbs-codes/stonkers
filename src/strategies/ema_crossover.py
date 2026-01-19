"""EMA Crossover Strategy."""
import pandas as pd
import ta
from typing import Optional, List
from src.strategies.base import Strategy
from src.data.models import Candle, Signal, Direction


class EmaCrossoverStrategy(Strategy):
    """
    EMA Crossover Strategy.

    Logic:
    - LONG: Fast EMA crosses above Slow EMA
    - SHORT: Fast EMA crosses below Slow EMA
    - Exit: Opposite crossover
    """

    name = "ema_crossover"
    description = "EMA crossover trend following strategy"
    required_history = 50

    def configure(self, params: dict) -> None:
        """Configure strategy parameters."""
        defaults = self.get_default_params()
        self.params = {**defaults, **params}
        # Update required history based on slow EMA
        self.required_history = self.params['slow_ema'] + 10

    def get_default_params(self) -> dict:
        """Return default parameters."""
        return {
            'fast_ema': 9,
            'slow_ema': 21
        }

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """
        Analyze candles and generate signal.

        Args:
            candles: List of historical candles (newest last)

        Returns:
            Signal object if conditions met, None otherwise
        """
        if not self.validate_candles(candles):
            return None

        # Convert to DataFrame
        df = pd.DataFrame([
            {'timestamp': c.timestamp, 'close': c.close}
            for c in candles
        ])

        # Calculate EMAs
        fast_period = self.params['fast_ema']
        slow_period = self.params['slow_ema']

        df['fast_ema'] = ta.trend.ema_indicator(df['close'], window=fast_period)
        df['slow_ema'] = ta.trend.ema_indicator(df['close'], window=slow_period)

        # Get current and previous values
        current_fast = df['fast_ema'].iloc[-1]
        current_slow = df['slow_ema'].iloc[-1]
        prev_fast = df['fast_ema'].iloc[-2]
        prev_slow = df['slow_ema'].iloc[-2]
        current_price = df['close'].iloc[-1]

        current_candle = candles[-1]

        # Check for bullish crossover (LONG)
        if prev_fast <= prev_slow and current_fast > current_slow:
            reasoning = (
                f"LONG signal: Fast EMA-{fast_period} ({current_fast:.2f}) "
                f"crossed above Slow EMA-{slow_period} ({current_slow:.2f}). "
                f"Previous: Fast {prev_fast:.2f}, Slow {prev_slow:.2f}. "
                f"Current price: {current_price:.2f}. "
                f"This indicates bullish momentum shift."
            )

            return Signal(
                timestamp=current_candle.timestamp,
                pair=current_candle.pair,
                direction=Direction.LONG,
                strength=0.7,
                strategy_name=self.name,
                reasoning=reasoning,
                indicators={
                    'price': current_price,
                    'fast_ema': current_fast,
                    'slow_ema': current_slow,
                    'prev_fast_ema': prev_fast,
                    'prev_slow_ema': prev_slow
                },
                timeframe=current_candle.timeframe
            )

        # Check for bearish crossover (SHORT)
        if prev_fast >= prev_slow and current_fast < current_slow:
            reasoning = (
                f"SHORT signal: Fast EMA-{fast_period} ({current_fast:.2f}) "
                f"crossed below Slow EMA-{slow_period} ({current_slow:.2f}). "
                f"Previous: Fast {prev_fast:.2f}, Slow {prev_slow:.2f}. "
                f"Current price: {current_price:.2f}. "
                f"This indicates bearish momentum shift."
            )

            return Signal(
                timestamp=current_candle.timestamp,
                pair=current_candle.pair,
                direction=Direction.SHORT,
                strength=0.7,
                strategy_name=self.name,
                reasoning=reasoning,
                indicators={
                    'price': current_price,
                    'fast_ema': current_fast,
                    'slow_ema': current_slow,
                    'prev_fast_ema': prev_fast,
                    'prev_slow_ema': prev_slow
                },
                timeframe=current_candle.timeframe
            )

        return None
