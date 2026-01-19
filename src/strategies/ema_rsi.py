"""EMA + RSI Mean Reversion Strategy."""
import pandas as pd
import ta
from typing import Optional, List
from datetime import datetime
from src.strategies.base import Strategy
from src.data.models import Candle, Signal, Direction


class EmaRsiStrategy(Strategy):
    """
    EMA + RSI Mean Reversion Strategy.

    Logic:
    - LONG: Price < EMA AND RSI crosses above oversold
    - SHORT: Price > EMA AND RSI crosses below overbought
    - Exit: RSI reaches neutral zone
    """

    name = "ema_rsi"
    description = "EMA + RSI mean reversion strategy"
    required_history = 100

    def configure(self, params: dict) -> None:
        """Configure strategy parameters."""
        defaults = self.get_default_params()
        self.params = {**defaults, **params}

    def get_default_params(self) -> dict:
        """Return default parameters."""
        return {
            'ema_period': 100,
            'rsi_period': 14,
            'rsi_oversold': 30,
            'rsi_overbought': 70,
            'rsi_neutral_low': 45,
            'rsi_neutral_high': 55
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
            {
                'timestamp': c.timestamp,
                'close': c.close,
                'high': c.high,
                'low': c.low
            }
            for c in candles
        ])

        # Calculate indicators
        ema_period = self.params['ema_period']
        rsi_period = self.params['rsi_period']

        df['ema'] = ta.trend.ema_indicator(df['close'], window=ema_period)
        df['rsi'] = ta.momentum.rsi(df['close'], window=rsi_period)

        # Get latest values
        current_price = df['close'].iloc[-1]
        current_ema = df['ema'].iloc[-1]
        current_rsi = df['rsi'].iloc[-1]
        prev_rsi = df['rsi'].iloc[-2]

        current_candle = candles[-1]

        # Check for LONG signal
        # Price below EMA AND RSI crossing above oversold
        if (current_price < current_ema and
            prev_rsi <= self.params['rsi_oversold'] and
            current_rsi > self.params['rsi_oversold']):

            reasoning = (
                f"LONG signal: RSI crossed above oversold level "
                f"(was {prev_rsi:.2f}, now {current_rsi:.2f}, threshold {self.params['rsi_oversold']}) "
                f"while price {current_price:.2f} is below EMA-{ema_period} at {current_ema:.2f}. "
                f"This suggests oversold conditions in a mean-reverting context."
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
                    'ema': current_ema,
                    'rsi': current_rsi,
                    'prev_rsi': prev_rsi
                },
                timeframe=current_candle.timeframe
            )

        # Check for SHORT signal
        # Price above EMA AND RSI crossing below overbought
        if (current_price > current_ema and
            prev_rsi >= self.params['rsi_overbought'] and
            current_rsi < self.params['rsi_overbought']):

            reasoning = (
                f"SHORT signal: RSI crossed below overbought level "
                f"(was {prev_rsi:.2f}, now {current_rsi:.2f}, threshold {self.params['rsi_overbought']}) "
                f"while price {current_price:.2f} is above EMA-{ema_period} at {current_ema:.2f}. "
                f"This suggests overbought conditions in a mean-reverting context."
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
                    'ema': current_ema,
                    'rsi': current_rsi,
                    'prev_rsi': prev_rsi
                },
                timeframe=current_candle.timeframe
            )

        # Check for EXIT signal (neutral zone)
        if (self.params['rsi_neutral_low'] <= current_rsi <= self.params['rsi_neutral_high']):
            reasoning = (
                f"EXIT signal: RSI at {current_rsi:.2f} entered neutral zone "
                f"({self.params['rsi_neutral_low']}-{self.params['rsi_neutral_high']})"
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
                    'ema': current_ema,
                    'rsi': current_rsi
                },
                timeframe=current_candle.timeframe
            )

        return None
