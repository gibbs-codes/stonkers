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
        volume_multiplier: float = 1.0,
        retest_enabled: bool = False,
        retest_lookback: int = 5,
        retest_tolerance_pct: float = 0.005,
    ):
        """Initialize Bollinger Band Squeeze strategy.

        Args:
            bb_period: Bollinger Band period (default 20)
            bb_std: Standard deviation multiplier (default 2.0)
            squeeze_threshold: Max bandwidth % for squeeze (default 0.04 = 4%)
            breakout_candles: Candles outside band to confirm (default 1)
            min_signal_strength: Minimum strength for signal (0.0-1.0)
            volume_multiplier: Minimum volume vs 20-period average (1.0 = off)
            retest_enabled: If True, wait for post-breakout retest of band before entry
            retest_lookback: Candles to look back for initial breakout
            retest_tolerance_pct: How close to the band the retest must come (e.g., 0.005 = 0.5%)
        """
        super().__init__(name="BB_SQUEEZE")
        self.bb_period = bb_period
        self.bb_std = bb_std
        self.squeeze_threshold = squeeze_threshold
        self.breakout_candles = breakout_candles
        self.min_signal_strength = (
            min_signal_strength
            if isinstance(min_signal_strength, Decimal)
            else Decimal(str(min_signal_strength))
        )
        self.volume_multiplier = volume_multiplier
        self.retest_enabled = retest_enabled
        self.retest_lookback = retest_lookback
        self.retest_tolerance_pct = retest_tolerance_pct

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
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

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
        current_volume = current['volume']
        avg_volume = current['avg_volume']

        # Volume confirmation (optional)
        volume_confirmed = True
        if self.volume_multiplier > 1.0:
            if pd.isna(avg_volume) or avg_volume == 0:
                return None
            volume_confirmed = current_volume > (avg_volume * self.volume_multiplier)

        # LONG: Price breaks above upper band after squeeze
        if (current_price > upper_band and
            previous['close'] <= previous['upper_band'] and
            volume_confirmed):
            # Calculate signal strength based on breakout strength
            breakout_pct = float((current_price - upper_band) / sma)
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
        if (current_price < lower_band and
            previous['close'] >= previous['lower_band'] and
            volume_confirmed):
            breakout_pct = float((lower_band - current_price) / sma)
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

        # Retest logic: look for prior breakout then pullback to band within tolerance
        if self.retest_enabled:
            tolerance_long = upper_band * self.retest_tolerance_pct
            tolerance_short = lower_band * self.retest_tolerance_pct
            window = max(self.retest_lookback, 2)
            recent_df = df.iloc[-window-1:]  # include prior candle for breakout

            # Find latest breakout candle within window
            breakout_long_idx = None
            breakout_short_idx = None
            for idx in range(len(recent_df)-1):
                row = recent_df.iloc[idx]
                prev_row = recent_df.iloc[idx-1] if idx > 0 else row
                if (row['close'] > row['upper_band'] and prev_row['close'] <= prev_row['upper_band'] and row['is_squeeze']):
                    breakout_long_idx = idx
                if (row['close'] < row['lower_band'] and prev_row['close'] >= prev_row['lower_band'] and row['is_squeeze']):
                    breakout_short_idx = idx

            # Current candle is last in recent_df
            curr = recent_df.iloc[-1]
            prev = recent_df.iloc[-2]

            # LONG retest: breakout happened, price pulled back to upper band zone and is bouncing
            if breakout_long_idx is not None:
                in_retest_zone = abs(curr['close'] - curr['upper_band']) <= tolerance_long
                bounce = curr['close'] > prev['close']
                if in_retest_zone and bounce and volume_confirmed:
                    strength = max(self.min_signal_strength, Decimal("0.7"))
                    return Signal(
                        pair=candles[-1].pair,
                        signal_type=SignalType.ENTRY_LONG,
                        strength=strength,
                        strategy_name=self.name,
                        reasoning=f"BB retest LONG: Breakout then pullback to upper band retest within {self.retest_tolerance_pct*100:.1f}%, volume_confirmed={volume_confirmed}",
                        timestamp=candles[-1].timestamp,
                        indicators={
                            'upper_band': float(curr['upper_band']),
                            'lower_band': float(curr['lower_band']),
                            'sma': float(curr['sma']),
                            'bandwidth': float(curr['bandwidth']),
                            'price': float(curr['close']),
                            'volume': float(curr['volume']),
                            'avg_volume': float(curr['avg_volume']) if not pd.isna(curr['avg_volume']) else 0.0,
                        }
                    )

            # SHORT retest: breakout down, pullback to lower band zone and rejection
            if breakout_short_idx is not None:
                in_retest_zone = abs(curr['close'] - curr['lower_band']) <= tolerance_short
                rejection = curr['close'] < prev['close']
                if in_retest_zone and rejection and volume_confirmed:
                    strength = max(self.min_signal_strength, Decimal("0.7"))
                    return Signal(
                        pair=candles[-1].pair,
                        signal_type=SignalType.ENTRY_SHORT,
                        strength=strength,
                        strategy_name=self.name,
                        reasoning=f"BB retest SHORT: Breakdown then pullback to lower band retest within {self.retest_tolerance_pct*100:.1f}%, volume_confirmed={volume_confirmed}",
                        timestamp=candles[-1].timestamp,
                        indicators={
                            'upper_band': float(curr['upper_band']),
                            'lower_band': float(curr['lower_band']),
                            'sma': float(curr['sma']),
                            'bandwidth': float(curr['bandwidth']),
                            'price': float(curr['close']),
                            'volume': float(curr['volume']),
                            'avg_volume': float(curr['avg_volume']) if not pd.isna(curr['avg_volume']) else 0.0,
                        }
                    )

        return None

    def diagnostics(self, candles: List[Candle]) -> dict:
        """Return current indicator values and condition statuses for debugging."""
        min_required = self.bb_period + 10
        if not candles or len(candles) < min_required:
            return {"status": f"need {min_required} candles, have {len(candles) if candles else 0}"}

        df = self._candles_to_df(candles)
        df['sma'] = df['close'].rolling(window=self.bb_period).mean()
        df['std'] = df['close'].rolling(window=self.bb_period).std()
        df['upper_band'] = df['sma'] + (df['std'] * self.bb_std)
        df['lower_band'] = df['sma'] - (df['std'] * self.bb_std)
        df['bandwidth'] = (df['upper_band'] - df['lower_band']) / df['sma']
        df['is_squeeze'] = df['bandwidth'] < self.squeeze_threshold

        current = df.iloc[-1]
        previous = df.iloc[-2]
        price = current['close']
        upper = current['upper_band']
        lower = current['lower_band']
        bw = current['bandwidth']
        recent_squeeze = df['is_squeeze'].iloc[-10:].any()

        broke_upper = price > upper and previous['close'] <= previous['upper_band']
        broke_lower = price < lower and previous['close'] >= previous['lower_band']

        return {
            "price": f"${price:.2f}",
            "upper_band": f"${upper:.2f}",
            "lower_band": f"${lower:.2f}",
            "bandwidth": f"{bw:.3f} (squeeze <{self.squeeze_threshold})",
            "recent_squeeze": f"{'YES' if recent_squeeze else 'NO'} (last 10 candles)",
            "broke_upper": f"{'PASS' if broke_upper else 'FAIL'}",
            "broke_lower": f"{'PASS' if broke_lower else 'FAIL'}",
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
                'volume': float(c.volume),
            }
            for c in candles
        ])
