"""Momentum Thrust Strategy.

Logic:
- Calculate Rate of Change (ROC) over N periods
- Detect momentum surges with volume confirmation
- LONG: ROC crosses above +threshold with volume spike
- SHORT: ROC crosses below -threshold with volume spike

Captures strong momentum moves with institutional participation.
"""
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class MomentumThrustStrategy(Strategy):
    """Momentum thrust strategy with volume confirmation."""

    def __init__(
        self,
        roc_period: int = 14,
        entry_threshold: float = 5.0,
        exit_threshold: float = 2.0,
        volume_multiplier: float = 1.5,
        min_signal_strength: float = 0.6,
    ):
        """Initialize Momentum Thrust strategy.

        Args:
            roc_period: Periods for Rate of Change calculation (default 14)
            entry_threshold: ROC percentage threshold for entry signals (default 5.0%)
            exit_threshold: ROC percentage for neutral zone (default 2.0%)
            volume_multiplier: Minimum volume vs 20-period average (default 1.5x)
            min_signal_strength: Minimum signal strength (0.0-1.0, default 0.6)
        """
        super().__init__(name="MOMENTUM_THRUST")
        self.roc_period = roc_period
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.volume_multiplier = volume_multiplier
        self.min_signal_strength = min_signal_strength

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for momentum thrust signals.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if momentum thrust detected with volume confirmation, None otherwise
        """
        # Need ROC period + 20 for volume average + 5 buffer for calculations
        min_required = self.roc_period + 25
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Calculate Rate of Change (ROC)
        # ROC = ((Close - Close[N periods ago]) / Close[N periods ago]) * 100
        df['roc'] = ((df['close'] - df['close'].shift(self.roc_period)) /
                     df['close'].shift(self.roc_period)) * 100

        # Calculate 20-period average volume
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

        # Get current and previous values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_roc = current['roc']
        previous_roc = previous['roc']
        current_volume = current['volume']
        avg_volume = current['avg_volume']

        # Skip if we don't have valid ROC or volume data
        if pd.isna(current_roc) or pd.isna(avg_volume) or avg_volume == 0:
            return None

        # Check for volume spike
        volume_spike = current_volume > (avg_volume * self.volume_multiplier)

        # LONG Signal: ROC crosses above +threshold with volume confirmation
        if (previous_roc <= self.entry_threshold and
            current_roc > self.entry_threshold and
            volume_spike):

            # Calculate signal strength based on ROC magnitude
            # Higher ROC = stronger signal, capped at 1.0
            roc_strength = min(1.0, current_roc / (self.entry_threshold * 2))
            strength = Decimal(str(max(self.min_signal_strength, roc_strength)))

            volume_ratio = current_volume / avg_volume

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Momentum thrust LONG: ROC crossed above +{self.entry_threshold}% (ROC: {current_roc:.2f}%) with {volume_ratio:.1f}x volume spike",
                timestamp=candles[-1].timestamp,
                indicators={
                    'roc': float(current_roc),
                    'roc_threshold': self.entry_threshold,
                    'volume': float(current_volume),
                    'avg_volume': float(avg_volume),
                    'volume_ratio': float(volume_ratio),
                }
            )

        # SHORT Signal: ROC crosses below -threshold with volume confirmation
        if (previous_roc >= -self.entry_threshold and
            current_roc < -self.entry_threshold and
            volume_spike):

            # Calculate signal strength based on ROC magnitude (absolute value)
            roc_strength = min(1.0, abs(current_roc) / (self.entry_threshold * 2))
            strength = Decimal(str(max(self.min_signal_strength, roc_strength)))

            volume_ratio = current_volume / avg_volume

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Momentum thrust SHORT: ROC crossed below -{self.entry_threshold}% (ROC: {current_roc:.2f}%) with {volume_ratio:.1f}x volume spike",
                timestamp=candles[-1].timestamp,
                indicators={
                    'roc': float(current_roc),
                    'roc_threshold': -self.entry_threshold,
                    'volume': float(current_volume),
                    'avg_volume': float(avg_volume),
                    'volume_ratio': float(volume_ratio),
                }
            )

        return None

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
                'volume': float(c.volume),
            }
            for c in candles
        ])
