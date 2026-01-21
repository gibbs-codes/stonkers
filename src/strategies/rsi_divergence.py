"""RSI Divergence Strategy.

Logic:
- Bullish Divergence: Price makes lower low, RSI makes higher low (momentum strengthening)
- Bearish Divergence: Price makes higher high, RSI makes lower high (momentum weakening)

Catches trend exhaustion and potential reversals.
"""
from decimal import Decimal
from typing import List, Optional, Tuple

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class RsiDivergenceStrategy(Strategy):
    """RSI divergence detection for reversal signals."""

    def __init__(
        self,
        rsi_period: int = 14,
        lookback: int = 10,
        min_signal_strength: Decimal = Decimal("0.7"),  # Higher threshold - quality over quantity
    ):
        """Initialize RSI Divergence strategy.

        Args:
            rsi_period: RSI calculation period (default 14)
            lookback: Candles to scan for divergence (default 10)
            min_signal_strength: Minimum strength for signal (default 0.7)
        """
        super().__init__(name="RSI_DIV")
        self.rsi_period = rsi_period
        self.lookback = lookback
        self.min_signal_strength = min_signal_strength

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for RSI divergence signals.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if divergence detected, None otherwise
        """
        # Need enough candles for RSI + lookback
        min_required = self.rsi_period + self.lookback + 5
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Calculate RSI
        df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)

        # Get recent window for divergence detection
        recent_df = df.iloc[-self.lookback:]

        # Find local highs and lows in both price and RSI
        price_highs, price_lows = self._find_local_extremes(recent_df['close'])
        rsi_highs, rsi_lows = self._find_local_extremes(recent_df['rsi'])

        # Check for bullish divergence (buy signal)
        bullish_div = self._check_bullish_divergence(
            recent_df, price_lows, rsi_lows
        )

        if bullish_div:
            strength, reasoning = bullish_div
            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=Decimal(str(strength)),
                strategy_name=self.name,
                reasoning=reasoning,
                timestamp=candles[-1].timestamp,
                indicators={
                    'rsi': float(recent_df['rsi'].iloc[-1]),
                    'price': float(recent_df['close'].iloc[-1]),
                }
            )

        # Check for bearish divergence (sell signal)
        bearish_div = self._check_bearish_divergence(
            recent_df, price_highs, rsi_highs
        )

        if bearish_div:
            strength, reasoning = bearish_div
            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=Decimal(str(strength)),
                strategy_name=self.name,
                reasoning=reasoning,
                timestamp=candles[-1].timestamp,
                indicators={
                    'rsi': float(recent_df['rsi'].iloc[-1]),
                    'price': float(recent_df['close'].iloc[-1]),
                }
            )

        return None

    def _find_local_extremes(self, series: pd.Series) -> Tuple[List[int], List[int]]:
        """Find local highs and lows in a series.

        Args:
            series: Price or indicator series

        Returns:
            Tuple of (high_indices, low_indices)
        """
        highs = []
        lows = []

        for i in range(1, len(series) - 1):
            # Local high: higher than neighbors
            if series.iloc[i] > series.iloc[i-1] and series.iloc[i] > series.iloc[i+1]:
                highs.append(i)

            # Local low: lower than neighbors
            if series.iloc[i] < series.iloc[i-1] and series.iloc[i] < series.iloc[i+1]:
                lows.append(i)

        return highs, lows

    def _check_bullish_divergence(
        self,
        df: pd.DataFrame,
        price_lows: List[int],
        rsi_lows: List[int]
    ) -> Optional[Tuple[float, str]]:
        """Check for bullish divergence.

        Bullish divergence: Price makes lower low, RSI makes higher low.

        Returns:
            Tuple of (strength, reasoning) if found, None otherwise
        """
        if len(price_lows) < 2 or len(rsi_lows) < 2:
            return None

        # Get last two lows
        last_price_low_idx = price_lows[-1]
        prev_price_low_idx = price_lows[-2]

        last_rsi_low_idx = rsi_lows[-1]
        prev_rsi_low_idx = rsi_lows[-2]

        # Check if close enough in time (within 3 candles)
        if abs(last_price_low_idx - last_rsi_low_idx) > 3:
            return None

        last_price_low = df['close'].iloc[last_price_low_idx]
        prev_price_low = df['close'].iloc[prev_price_low_idx]
        last_rsi_low = df['rsi'].iloc[last_rsi_low_idx]
        prev_rsi_low = df['rsi'].iloc[prev_rsi_low_idx]

        # Bullish divergence condition
        if last_price_low < prev_price_low and last_rsi_low > prev_rsi_low:
            # Calculate strength based on divergence magnitude
            price_drop_pct = (prev_price_low - last_price_low) / prev_price_low
            rsi_rise_pct = (last_rsi_low - prev_rsi_low) / 100  # RSI is 0-100

            strength = min(1.0, 0.7 + (price_drop_pct + rsi_rise_pct) * 2)

            reasoning = (
                f"Bullish divergence: Price lower low ${last_price_low:.2f} < ${prev_price_low:.2f}, "
                f"but RSI higher low {last_rsi_low:.1f} > {prev_rsi_low:.1f} "
                f"(momentum strengthening despite lower price)"
            )

            return (strength, reasoning)

        return None

    def _check_bearish_divergence(
        self,
        df: pd.DataFrame,
        price_highs: List[int],
        rsi_highs: List[int]
    ) -> Optional[Tuple[float, str]]:
        """Check for bearish divergence.

        Bearish divergence: Price makes higher high, RSI makes lower high.

        Returns:
            Tuple of (strength, reasoning) if found, None otherwise
        """
        if len(price_highs) < 2 or len(rsi_highs) < 2:
            return None

        # Get last two highs
        last_price_high_idx = price_highs[-1]
        prev_price_high_idx = price_highs[-2]

        last_rsi_high_idx = rsi_highs[-1]
        prev_rsi_high_idx = rsi_highs[-2]

        # Check if close enough in time
        if abs(last_price_high_idx - last_rsi_high_idx) > 3:
            return None

        last_price_high = df['close'].iloc[last_price_high_idx]
        prev_price_high = df['close'].iloc[prev_price_high_idx]
        last_rsi_high = df['rsi'].iloc[last_rsi_high_idx]
        prev_rsi_high = df['rsi'].iloc[prev_rsi_high_idx]

        # Bearish divergence condition
        if last_price_high > prev_price_high and last_rsi_high < prev_rsi_high:
            # Calculate strength based on divergence magnitude
            price_rise_pct = (last_price_high - prev_price_high) / prev_price_high
            rsi_drop_pct = (prev_rsi_high - last_rsi_high) / 100

            strength = min(1.0, 0.7 + (price_rise_pct + rsi_drop_pct) * 2)

            reasoning = (
                f"Bearish divergence: Price higher high ${last_price_high:.2f} > ${prev_price_high:.2f}, "
                f"but RSI lower high {last_rsi_high:.1f} < {prev_rsi_high:.1f} "
                f"(momentum weakening despite higher price)"
            )

            return (strength, reasoning)

        return None

    def _candles_to_df(self, candles: List[Candle]) -> pd.DataFrame:
        """Convert candles to pandas DataFrame."""
        return pd.DataFrame([
            {'close': float(c.close)}
            for c in candles
        ])

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi
