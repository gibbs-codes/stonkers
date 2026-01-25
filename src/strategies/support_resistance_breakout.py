"""Support/Resistance Breakout Strategy with Retest Confirmation.

Logic (3 Phases):
1. IDENTIFY: Find key support/resistance levels from swing highs/lows
2. BREAKOUT: Detect when price breaks through a level with volume
3. RETEST: Wait for pullback to retest broken level before entering

Only signals on confirmed retest + bounce/rejection for high-probability trades.
"""
from decimal import Decimal
from typing import List, Optional, Dict, Tuple

import pandas as pd
import numpy as np

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class SupportResistanceBreakoutStrategy(Strategy):
    """Support/Resistance breakout with retest confirmation strategy."""

    def __init__(
        self,
        lookback_period: int = 80,
        level_tolerance: float = 0.012,
        min_touches: int = 2,
        volume_multiplier: float = 1.15,
        retest_candles: int = 5,
        retest_tolerance: float = 0.01,
        min_signal_strength: float = 0.65,
    ):
        """Initialize Support/Resistance Breakout strategy.

        Args:
            lookback_period: Candles to scan for levels (default 100)
            level_tolerance: Price tolerance for clustering levels (default 0.01 = 1%)
            min_touches: Minimum times level must be tested (default 2)
            volume_multiplier: Volume confirmation on breakout (default 1.3x)
            retest_candles: Max candles to wait for retest (default 8)
            retest_tolerance: Price tolerance for retest (default 0.005 = 0.5%)
            min_signal_strength: Minimum signal strength (default 0.7)
        """
        super().__init__(name="SR_BREAKOUT")
        self.lookback_period = lookback_period
        self.level_tolerance = level_tolerance
        self.min_touches = min_touches
        self.volume_multiplier = volume_multiplier
        self.retest_candles = retest_candles
        self.retest_tolerance = retest_tolerance
        self.min_signal_strength = min_signal_strength

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for S/R breakout with retest confirmation.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if breakout + retest confirmed, None otherwise
        """
        # Need lookback + retest buffer
        min_required = self.lookback_period + self.retest_candles + 5
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Phase 1: Identify support/resistance levels
        levels = self._find_support_resistance_levels(df)

        if not levels['resistance'] and not levels['support']:
            return None

        # Calculate 20-period average volume for confirmation
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

        # Phase 2 & 3: Check for breakout + retest in recent candles
        # Look at last retest_candles + 1 for breakout and retest pattern
        recent_window = min(self.retest_candles + 5, len(df))
        recent_df = df.iloc[-recent_window:]

        # Check for resistance breakout + retest (LONG signal)
        long_signal = self._check_resistance_breakout_retest(
            recent_df, levels['resistance'], candles
        )
        if long_signal:
            return long_signal

        # Check for support breakdown + retest (SHORT signal)
        short_signal = self._check_support_breakdown_retest(
            recent_df, levels['support'], candles
        )
        if short_signal:
            return short_signal

        return None

    def _find_swing_highs(self, df: pd.DataFrame) -> List[int]:
        """Find indices of local swing highs.

        Args:
            df: DataFrame with price data

        Returns:
            List of indices where local highs occur
        """
        highs = []
        for i in range(1, len(df) - 1):
            if df['high'].iloc[i] > df['high'].iloc[i-1] and \
               df['high'].iloc[i] > df['high'].iloc[i+1]:
                highs.append(i)
        return highs

    def _find_swing_lows(self, df: pd.DataFrame) -> List[int]:
        """Find indices of local swing lows.

        Args:
            df: DataFrame with price data

        Returns:
            List of indices where local lows occur
        """
        lows = []
        for i in range(1, len(df) - 1):
            if df['low'].iloc[i] < df['low'].iloc[i-1] and \
               df['low'].iloc[i] < df['low'].iloc[i+1]:
                lows.append(i)
        return lows

    def _cluster_levels(self, levels: List[float]) -> List[float]:
        """Group nearby price levels within tolerance.

        Args:
            levels: List of price levels to cluster

        Returns:
            List of clustered levels (averaged within tolerance)
        """
        if not levels:
            return []

        sorted_levels = sorted(levels)
        clustered = []
        current_cluster = [sorted_levels[0]]

        for level in sorted_levels[1:]:
            # Check if within tolerance of cluster average
            cluster_avg = sum(current_cluster) / len(current_cluster)
            if abs(level - cluster_avg) / cluster_avg <= self.level_tolerance:
                current_cluster.append(level)
            else:
                # Finalize current cluster if it has enough touches
                if len(current_cluster) >= self.min_touches:
                    clustered.append(sum(current_cluster) / len(current_cluster))
                current_cluster = [level]

        # Don't forget last cluster
        if len(current_cluster) >= self.min_touches:
            clustered.append(sum(current_cluster) / len(current_cluster))

        return clustered

    def _find_support_resistance_levels(self, df: pd.DataFrame) -> Dict[str, List[float]]:
        """Identify support and resistance levels from swing points.

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Dict with 'resistance' and 'support' lists of price levels
        """
        # Use lookback window
        lookback_df = df.iloc[-self.lookback_period:] if len(df) > self.lookback_period else df

        # Find swing highs and lows
        swing_high_indices = self._find_swing_highs(lookback_df)
        swing_low_indices = self._find_swing_lows(lookback_df)

        # Extract price levels
        resistance_levels = [lookback_df['high'].iloc[i] for i in swing_high_indices]
        support_levels = [lookback_df['low'].iloc[i] for i in swing_low_indices]

        # Cluster nearby levels
        clustered_resistance = self._cluster_levels(resistance_levels)
        clustered_support = self._cluster_levels(support_levels)

        return {
            'resistance': clustered_resistance,
            'support': clustered_support,
        }

    def _check_resistance_breakout_retest(
        self,
        recent_df: pd.DataFrame,
        resistance_levels: List[float],
        candles: List[Candle]
    ) -> Optional[Signal]:
        """Check for resistance breakout followed by successful retest.

        LONG signal logic:
        1. Find a candle that broke above resistance with volume
        2. Find subsequent retest (pullback to resistance from above)
        3. Confirm bounce (price moves back up after retest)

        Args:
            recent_df: Recent candles DataFrame
            resistance_levels: List of resistance price levels
            candles: Original candle list for signal creation

        Returns:
            Signal if breakout + retest confirmed, None otherwise
        """
        if not resistance_levels:
            return None

        current_price = recent_df['close'].iloc[-1]

        # Look for breakout + retest pattern in recent window
        for level in resistance_levels:
            # Find breakout candle (close above level with volume)
            breakout_idx = None
            for i in range(len(recent_df) - self.retest_candles, len(recent_df) - 2):
                if i < 1:
                    continue

                candle = recent_df.iloc[i]
                prev_candle = recent_df.iloc[i-1]

                # Breakout: previous close below, current close above
                if (prev_candle['close'] <= level and
                    candle['close'] > level and
                    candle['volume'] > candle['avg_volume'] * self.volume_multiplier):
                    breakout_idx = i
                    break

            if breakout_idx is None:
                continue

            # Look for retest after breakout (within retest_candles)
            retest_idx = None
            for i in range(breakout_idx + 1, min(breakout_idx + self.retest_candles, len(recent_df))):
                candle = recent_df.iloc[i]

                # Retest: price pulls back close to level (within tolerance)
                retest_distance = abs(candle['low'] - level) / level
                if retest_distance <= self.retest_tolerance:
                    retest_idx = i
                    break

            if retest_idx is None:
                continue

            # Confirm bounce: price moved back up after retest
            # Check if current price or recent candles show upward movement
            if retest_idx < len(recent_df) - 1:
                retest_low = recent_df.iloc[retest_idx]['low']
                subsequent_highs = [recent_df.iloc[j]['high'] for j in range(retest_idx + 1, len(recent_df))]

                if subsequent_highs and max(subsequent_highs) > retest_low:
                    # Successful retest + bounce confirmed!
                    breakout_price = recent_df.iloc[breakout_idx]['close']
                    retest_price = recent_df.iloc[retest_idx]['low']
                    bounce_height = current_price - retest_price

                    # Calculate signal strength based on bounce strength and volume
                    bounce_pct = (bounce_height / retest_price) * 100
                    strength = min(1.0, self.min_signal_strength + bounce_pct * 2)

                    return Signal(
                        pair=candles[-1].pair,
                        signal_type=SignalType.ENTRY_LONG,
                        strength=Decimal(str(strength)),
                        strategy_name=self.name,
                        reasoning=f"Resistance breakout + retest LONG: Broke ${level:.2f} at ${breakout_price:.2f}, "
                                  f"retested at ${retest_price:.2f}, bounced to ${current_price:.2f}",
                        timestamp=candles[-1].timestamp,
                        indicators={
                            'level_price': float(level),
                            'breakout_price': float(breakout_price),
                            'retest_price': float(retest_price),
                            'current_price': float(current_price),
                            'bounce_pct': float(bounce_pct),
                        }
                    )

        return None

    def _check_support_breakdown_retest(
        self,
        recent_df: pd.DataFrame,
        support_levels: List[float],
        candles: List[Candle]
    ) -> Optional[Signal]:
        """Check for support breakdown followed by successful retest.

        SHORT signal logic:
        1. Find a candle that broke below support with volume
        2. Find subsequent retest (rally back to support from below)
        3. Confirm rejection (price moves back down after retest)

        Args:
            recent_df: Recent candles DataFrame
            support_levels: List of support price levels
            candles: Original candle list for signal creation

        Returns:
            Signal if breakdown + retest confirmed, None otherwise
        """
        if not support_levels:
            return None

        current_price = recent_df['close'].iloc[-1]

        # Look for breakdown + retest pattern
        for level in support_levels:
            # Find breakdown candle (close below level with volume)
            breakdown_idx = None
            for i in range(len(recent_df) - self.retest_candles, len(recent_df) - 2):
                if i < 1:
                    continue

                candle = recent_df.iloc[i]
                prev_candle = recent_df.iloc[i-1]

                # Breakdown: previous close above, current close below
                if (prev_candle['close'] >= level and
                    candle['close'] < level and
                    candle['volume'] > candle['avg_volume'] * self.volume_multiplier):
                    breakdown_idx = i
                    break

            if breakdown_idx is None:
                continue

            # Look for retest after breakdown
            retest_idx = None
            for i in range(breakdown_idx + 1, min(breakdown_idx + self.retest_candles, len(recent_df))):
                candle = recent_df.iloc[i]

                # Retest: price rallies back close to level (within tolerance)
                retest_distance = abs(candle['high'] - level) / level
                if retest_distance <= self.retest_tolerance:
                    retest_idx = i
                    break

            if retest_idx is None:
                continue

            # Confirm rejection: price moved back down after retest
            if retest_idx < len(recent_df) - 1:
                retest_high = recent_df.iloc[retest_idx]['high']
                subsequent_lows = [recent_df.iloc[j]['low'] for j in range(retest_idx + 1, len(recent_df))]

                if subsequent_lows and min(subsequent_lows) < retest_high:
                    # Successful retest + rejection confirmed!
                    breakdown_price = recent_df.iloc[breakdown_idx]['close']
                    retest_price = recent_df.iloc[retest_idx]['high']
                    rejection_depth = retest_price - current_price

                    # Calculate signal strength
                    rejection_pct = (rejection_depth / retest_price) * 100
                    strength = min(1.0, self.min_signal_strength + rejection_pct * 2)

                    return Signal(
                        pair=candles[-1].pair,
                        signal_type=SignalType.ENTRY_SHORT,
                        strength=Decimal(str(strength)),
                        strategy_name=self.name,
                        reasoning=f"Support breakdown + retest SHORT: Broke ${level:.2f} at ${breakdown_price:.2f}, "
                                  f"retested at ${retest_price:.2f}, rejected to ${current_price:.2f}",
                        timestamp=candles[-1].timestamp,
                        indicators={
                            'level_price': float(level),
                            'breakout_price': float(breakdown_price),
                            'retest_price': float(retest_price),
                            'current_price': float(current_price),
                            'rejection_pct': float(rejection_pct),
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
                'timestamp': c.timestamp,
                'open': float(c.open),
                'high': float(c.high),
                'low': float(c.low),
                'close': float(c.close),
                'volume': float(c.volume),
            }
            for c in candles
        ])
