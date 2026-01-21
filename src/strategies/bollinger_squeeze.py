"""Bollinger Band Squeeze Strategy.

Logic:
- Detect squeeze: Band width < threshold (volatility compressed)
- LONG: After squeeze, price closes above upper band
- SHORT: After squeeze, price closes below lower band

Trades volatility breakouts after periods of consolidation.
"""
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class BollingerSqueezeStrategy(Strategy):
    """Bollinger Band squeeze breakout strategy."""

    def __init__(
        self,
        bb_period: int = 20,
        bb_std: float = 2.0,
        squeeze_threshold: float = 0.04,  # 4% bandwidth = squeeze
        breakout_candles: int = 1,
        min_signal_strength: Decimal = Decimal("0.6"),
    ):
        """Initialize Bollinger Band Squeeze strategy.

        Args:
            bb_period: Bollinger Band period (default 20)
            bb_std: Standard deviation multiplier (default 2.0)
            squeeze_threshold: Max bandwidth % for squeeze (default 0.04 = 4%)
            breakout_candles: Candles outside band to confirm (default 1)
            min_signal_strength: Minimum strength for signal (0.0-1.0)
        """
        super().__init__(name="BB_SQUEEZE")
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_threshold = squeeze_threshold
        self.breakout_candles = breakout_candles
        self.min_signal_strength = min_signal_strength

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for Bollinger Band squeeze breakouts.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if breakout detected after squeeze, None otherwise
        """
        # Need enough candles for BB calculation + squeeze detection
        min_required = self.bb_period + 10
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Calculate Bollinger Bands
        df['sma'] = df['close'].rolling(window=self.bb_period).mean()
        df['std'] = df['close'].rolling(window=self.bb_period).std()
        df['upper_band'] = df['sma'] + (df['std'] * self.bb_std)
        df['lower_band'] = df['sma'] - (df['std'] * self.bb_std)

        # Calculate bandwidth (volatility indicator)
        df['bandwidth'] = (df['upper_band'] - df['lower_band']) / df['sma']

        # Detect squeeze: bandwidth below threshold
        df['is_squeeze'] = df['bandwidth'] < self.squeeze_threshold

        # Get recent values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        # Check if we HAD a squeeze recently (last 5-10 candles)
        recent_squeeze = df['is_squeeze'].iloc[-10:].any()

        if not recent_squeeze:
            return None  # No recent squeeze, no setup

        current_price = current['close']
        upper_band = current['upper_band']
        lower_band = current['lower_band']
        sma = current['sma']
        bandwidth = current['bandwidth']

        # LONG: Price breaks above upper band after squeeze
        if current_price > upper_band and previous['close'] <= previous['upper_band']:
            # Calculate signal strength based on breakout strength
            breakout_pct = (current_price - upper_band) / sma
            # Stronger breakout = higher strength
            strength = min(
                Decimal("1.0"),
                self.min_signal_strength + Decimal(str(breakout_pct * 10))
            )

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Bollinger breakout LONG: Price ${current_price:.2f} broke above upper band ${upper_band:.2f} after squeeze (bandwidth: {bandwidth:.3f})",
                timestamp=candles[-1].timestamp,
                indicators={
                    'upper_band': float(upper_band),
                    'lower_band': float(lower_band),
                    'sma': float(sma),
                    'bandwidth': float(bandwidth),
                    'price': float(current_price),
                }
            )

        # SHORT: Price breaks below lower band after squeeze
        if current_price < lower_band and previous['close'] >= previous['lower_band']:
            breakout_pct = (lower_band - current_price) / sma
            strength = min(
                Decimal("1.0"),
                self.min_signal_strength + Decimal(str(breakout_pct * 10))
            )

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Bollinger breakout SHORT: Price ${current_price:.2f} broke below lower band ${lower_band:.2f} after squeeze (bandwidth: {bandwidth:.3f})",
                timestamp=candles[-1].timestamp,
                indicators={
                    'upper_band': float(upper_band),
                    'lower_band': float(lower_band),
                    'sma': float(sma),
                    'bandwidth': float(bandwidth),
                    'price': float(current_price),
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
            }
            for c in candles
        ])
