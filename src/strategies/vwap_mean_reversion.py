"""VWAP Mean Reversion Strategy.

Logic:
- Calculate Volume-Weighted Average Price (VWAP) over rolling window
- Calculate standard deviation of price distance from VWAP
- LONG: Price drops below VWAP - (std_multiplier * StdDev) with volume confirmation
- SHORT: Price rises above VWAP + (std_multiplier * StdDev) with volume confirmation

Mean reversion strategy betting on price returning to VWAP institutional anchor.
"""
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class VwapMeanReversionStrategy(Strategy):
    """VWAP mean reversion strategy with volume confirmation."""

    def __init__(
        self,
        vwap_period: int = 45,
        std_multiplier: float = 1.3,
        volume_threshold: float = 1.0,
        min_signal_strength: float = 0.5,
        stretch_factor: float = 0.8,
    ):
        """Initialize VWAP Mean Reversion strategy.

        Args:
            vwap_period: Lookback period for rolling VWAP (default 50)
            std_multiplier: Standard deviations from VWAP for entry (default 2.0)
            volume_threshold: Volume must be this multiple of 20-period avg (default 1.5x)
            min_signal_strength: Minimum signal strength (0.0-1.0, default 0.6)
        """
        super().__init__(name="VWAP_MEAN_REV")
        self.vwap_period = vwap_period
        self.std_multiplier = std_multiplier
        self.volume_threshold = volume_threshold
        self.min_signal_strength = min_signal_strength
        self.stretch_factor = stretch_factor

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for VWAP mean reversion signals.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if mean reversion setup detected with volume confirmation, None otherwise
        """
        # Need vwap_period + 20 for volume average + buffer
        min_required = self.vwap_period + 20
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame
        df = self._candles_to_df(candles)

        # Calculate VWAP
        df['vwap'] = self._calculate_vwap(df)

        # Calculate distance from VWAP
        df['distance_from_vwap'] = df['close'] - df['vwap']

        # Calculate standard deviation of distance from VWAP
        df['std_dev'] = df['distance_from_vwap'].rolling(window=self.vwap_period).std()

        # Calculate upper and lower bands
        df['upper_band'] = df['vwap'] + (self.std_multiplier * df['std_dev'])
        df['lower_band'] = df['vwap'] - (self.std_multiplier * df['std_dev'])

        # Calculate 20-period average volume for confirmation
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

        # Get current and previous values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_price = current['close']
        current_vwap = current['vwap']
        current_std = current['std_dev']
        lower_band = current['lower_band']
        upper_band = current['upper_band']
        current_volume = current['volume']
        avg_volume = current['avg_volume']

        # Skip if we don't have valid data
        if pd.isna(current_vwap) or pd.isna(current_std) or pd.isna(avg_volume) or avg_volume == 0:
            return None

        # Check for volume confirmation
        volume_confirmed = current_volume > (avg_volume * self.volume_threshold)

        # Calculate distance from VWAP in standard deviations
        distance_in_std = abs(current_price - current_vwap) / current_std if current_std > 0 else 0
        # Require a minimum stretch beyond band to avoid tiny pierces
        stretched_enough = distance_in_std >= (self.std_multiplier * self.stretch_factor)

        # LONG Signal: Price crosses below lower band with volume confirmation
        # Mean reversion bet: price will revert back up to VWAP
        if (previous['close'] >= previous['lower_band'] and
            current_price < lower_band and
            volume_confirmed and
            stretched_enough):

            # Signal strength based on how far from VWAP (farther = stronger mean reversion setup)
            # But cap it - too far might indicate trend change rather than reversion
            strength_factor = min(1.0, distance_in_std / (self.std_multiplier * 1.5))
            strength = Decimal(str(max(self.min_signal_strength, strength_factor)))

            volume_ratio = current_volume / avg_volume
            distance_pct = ((current_price - current_vwap) / current_vwap) * 100

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Mean reversion LONG: Price ${current_price:.2f} crossed below VWAP-{self.std_multiplier}σ (VWAP: ${current_vwap:.2f}, {distance_pct:.2f}% below) with {volume_ratio:.1f}x volume",
                timestamp=candles[-1].timestamp,
                indicators={
                    'vwap': float(current_vwap),
                    'std_dev': float(current_std),
                    'lower_band': float(lower_band),
                    'upper_band': float(upper_band),
                    'distance_from_vwap': float(current_price - current_vwap),
                    'distance_in_std': float(distance_in_std),
                    'volume': float(current_volume),
                    'avg_volume': float(avg_volume),
                    'volume_ratio': float(volume_ratio),
                },
                stop_loss_price=Decimal(str(max(0.0, float(lower_band - (current_std * 0.5))))),
                take_profit_price=Decimal(str(current_vwap)),
            )

        # SHORT Signal: Price crosses above upper band with volume confirmation
        # Mean reversion bet: price will revert back down to VWAP
        if (previous['close'] <= previous['upper_band'] and
            current_price > upper_band and
            volume_confirmed and
            stretched_enough):

            # Signal strength based on distance from VWAP
            strength_factor = min(1.0, distance_in_std / (self.std_multiplier * 1.5))
            strength = Decimal(str(max(self.min_signal_strength, strength_factor)))

            volume_ratio = current_volume / avg_volume
            distance_pct = ((current_price - current_vwap) / current_vwap) * 100

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Mean reversion SHORT: Price ${current_price:.2f} crossed above VWAP+{self.std_multiplier}σ (VWAP: ${current_vwap:.2f}, {distance_pct:.2f}% above) with {volume_ratio:.1f}x volume",
                timestamp=candles[-1].timestamp,
                indicators={
                    'vwap': float(current_vwap),
                    'std_dev': float(current_std),
                    'lower_band': float(lower_band),
                    'upper_band': float(upper_band),
                    'distance_from_vwap': float(current_price - current_vwap),
                    'distance_in_std': float(distance_in_std),
                    'volume': float(current_volume),
                    'avg_volume': float(avg_volume),
                    'volume_ratio': float(volume_ratio),
                },
                stop_loss_price=Decimal(str(current_price + (current_std * 0.5))),
                take_profit_price=Decimal(str(current_vwap)),
            )

        return None

    def diagnostics(self, candles: List[Candle]) -> dict:
        """Return current indicator values and condition statuses for debugging."""
        min_required = self.vwap_period + 20
        if not candles or len(candles) < min_required:
            return {"status": f"need {min_required} candles, have {len(candles) if candles else 0}"}

        df = self._candles_to_df(candles)
        df['vwap'] = self._calculate_vwap(df)
        df['distance_from_vwap'] = df['close'] - df['vwap']
        df['std_dev'] = df['distance_from_vwap'].rolling(window=self.vwap_period).std()
        df['upper_band'] = df['vwap'] + (self.std_multiplier * df['std_dev'])
        df['lower_band'] = df['vwap'] - (self.std_multiplier * df['std_dev'])
        df['avg_volume'] = df['volume'].rolling(window=20).mean()

        current = df.iloc[-1]
        previous = df.iloc[-2]
        price = current['close']
        vwap = current['vwap']
        std = current['std_dev']
        upper = current['upper_band']
        lower = current['lower_band']
        vol = current['volume']
        avg_vol = current['avg_volume']

        if pd.isna(vwap) or pd.isna(std) or pd.isna(avg_vol) or avg_vol == 0:
            return {"status": "insufficient data for VWAP calculation"}

        distance_in_std = abs(price - vwap) / std if std > 0 else 0
        stretched = distance_in_std >= (self.std_multiplier * self.stretch_factor)
        vol_confirmed = vol > (avg_vol * self.volume_threshold)
        crossed_lower = previous['close'] >= previous['lower_band'] and price < lower
        crossed_upper = previous['close'] <= previous['upper_band'] and price > upper

        return {
            "price": f"${price:.2f}",
            "vwap": f"${vwap:.2f}",
            "upper_band": f"${upper:.2f}",
            "lower_band": f"${lower:.2f}",
            "distance": f"{distance_in_std:.2f}σ (need >={self.std_multiplier * self.stretch_factor:.2f}σ)",
            "stretched": f"{'PASS' if stretched else 'FAIL'}",
            "volume": f"{vol:.0f} vs avg {avg_vol:.0f} ({vol/avg_vol:.1f}x, need >{self.volume_threshold}x)",
            "vol_confirmed": f"{'PASS' if vol_confirmed else 'FAIL'}",
            "crossed_lower": f"{'PASS' if crossed_lower else 'FAIL'}",
            "crossed_upper": f"{'PASS' if crossed_upper else 'FAIL'}",
        }

    def _calculate_vwap(self, df: pd.DataFrame) -> pd.Series:
        """Calculate VWAP using typical price over rolling window.

        VWAP = Sum(Typical Price * Volume) / Sum(Volume)
        Typical Price = (High + Low + Close) / 3

        Args:
            df: DataFrame with OHLCV data

        Returns:
            Series of VWAP values
        """
        # Calculate typical price
        typical_price = (df['high'] + df['low'] + df['close']) / 3

        # Calculate rolling VWAP
        # For 24/7 crypto markets, we use a rolling window approach
        vwap = (typical_price * df['volume']).rolling(window=self.vwap_period).sum() / \
               df['volume'].rolling(window=self.vwap_period).sum()

        return vwap

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
