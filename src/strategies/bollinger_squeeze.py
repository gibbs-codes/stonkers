"""Bollinger Band Squeeze Strategy."""
import pandas as pd
import ta
from typing import Optional, List
from src.strategies.base import Strategy
from src.data.models import Candle, Signal, Direction


class BollingerSqueezeStrategy(Strategy):
    """
    Bollinger Band Squeeze Strategy.

    Logic:
    - Detect squeeze: bandwidth < threshold
    - LONG: Breakout above upper band after squeeze
    - SHORT: Breakout below lower band after squeeze
    - Exit: Price returns inside bands
    """

    name = "bollinger_squeeze"
    description = "Bollinger Band squeeze breakout strategy"
    required_history = 50

    def configure(self, params: dict) -> None:
        """Configure strategy parameters."""
        defaults = self.get_default_params()
        self.params = {**defaults, **params}
        self.required_history = self.params['bb_period'] + 10

    def get_default_params(self) -> dict:
        """Return default parameters."""
        return {
            'bb_period': 20,
            'bb_std': 2.0,
            'squeeze_threshold': 0.04
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

        # Calculate Bollinger Bands
        bb_period = self.params['bb_period']
        bb_std = self.params['bb_std']

        bb_indicator = ta.volatility.BollingerBands(
            df['close'],
            window=bb_period,
            window_dev=bb_std
        )

        df['bb_upper'] = bb_indicator.bollinger_hband()
        df['bb_middle'] = bb_indicator.bollinger_mavg()
        df['bb_lower'] = bb_indicator.bollinger_lband()
        df['bb_bandwidth'] = bb_indicator.bollinger_wband()

        # Get current values
        current_price = df['close'].iloc[-1]
        current_upper = df['bb_upper'].iloc[-1]
        current_middle = df['bb_middle'].iloc[-1]
        current_lower = df['bb_lower'].iloc[-1]
        current_bandwidth = df['bb_bandwidth'].iloc[-1]

        # Check for squeeze in recent candles
        recent_bandwidth = df['bb_bandwidth'].iloc[-10:]
        had_squeeze = (recent_bandwidth < self.params['squeeze_threshold']).any()

        current_candle = candles[-1]

        # LONG: Breakout above upper band after squeeze
        if had_squeeze and current_price > current_upper:
            reasoning = (
                f"LONG signal: Price {current_price:.2f} broke above upper Bollinger Band "
                f"({current_upper:.2f}) after squeeze period. "
                f"Current bandwidth: {current_bandwidth:.4f}, "
                f"squeeze threshold: {self.params['squeeze_threshold']}. "
                f"This suggests a bullish breakout from consolidation."
            )

            return Signal(
                timestamp=current_candle.timestamp,
                pair=current_candle.pair,
                direction=Direction.LONG,
                strength=0.75,
                strategy_name=self.name,
                reasoning=reasoning,
                indicators={
                    'price': current_price,
                    'bb_upper': current_upper,
                    'bb_middle': current_middle,
                    'bb_lower': current_lower,
                    'bandwidth': current_bandwidth
                },
                timeframe=current_candle.timeframe
            )

        # SHORT: Breakout below lower band after squeeze
        if had_squeeze and current_price < current_lower:
            reasoning = (
                f"SHORT signal: Price {current_price:.2f} broke below lower Bollinger Band "
                f"({current_lower:.2f}) after squeeze period. "
                f"Current bandwidth: {current_bandwidth:.4f}, "
                f"squeeze threshold: {self.params['squeeze_threshold']}. "
                f"This suggests a bearish breakout from consolidation."
            )

            return Signal(
                timestamp=current_candle.timestamp,
                pair=current_candle.pair,
                direction=Direction.SHORT,
                strength=0.75,
                strategy_name=self.name,
                reasoning=reasoning,
                indicators={
                    'price': current_price,
                    'bb_upper': current_upper,
                    'bb_middle': current_middle,
                    'bb_lower': current_lower,
                    'bandwidth': current_bandwidth
                },
                timeframe=current_candle.timeframe
            )

        # EXIT: Price returns inside bands
        if current_lower < current_price < current_upper:
            # Only signal exit if we were recently outside bands
            prev_price = df['close'].iloc[-2]
            was_outside = prev_price >= current_upper or prev_price <= current_lower

            if was_outside:
                reasoning = (
                    f"EXIT signal: Price {current_price:.2f} returned inside Bollinger Bands "
                    f"(lower: {current_lower:.2f}, upper: {current_upper:.2f})"
                )

                return Signal(
                    timestamp=current_candle.timestamp,
                    pair=current_candle.pair,
                    direction=Direction.NEUTRAL,
                    strength=0.6,
                    strategy_name=self.name,
                    reasoning=reasoning,
                    indicators={
                        'price': current_price,
                        'bb_upper': current_upper,
                        'bb_middle': current_middle,
                        'bb_lower': current_lower,
                        'bandwidth': current_bandwidth
                    },
                    timeframe=current_candle.timeframe
                )

        return None
