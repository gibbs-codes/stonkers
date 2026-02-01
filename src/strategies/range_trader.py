"""Range trading strategy using RangeDetector.

Trades bounces inside a detected range; stands aside when trending.
"""
from decimal import Decimal
from typing import List, Optional

from src.analysis.range_detector import RangeDetector
from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class RangeTraderStrategy(Strategy):
    """Mean-reversion inside detected ranges."""

    def __init__(
        self,
        range_lookback: int = 20,
        support_tolerance: float = 0.003,
        resistance_tolerance: float = 0.003,
        min_range_touches: int = 4,
        adx_period: int = 14,
        adx_threshold: float = 20.0,
        min_signal_strength: float = 0.55,
    ):
        super().__init__(name="RANGE_TRADER")
        self.range_lookback = range_lookback
        self.support_tolerance = support_tolerance
        self.resistance_tolerance = resistance_tolerance
        self.min_range_touches = min_range_touches
        self.min_signal_strength = Decimal(str(min_signal_strength))
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.detector = RangeDetector()

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Identify range trades; no trades when trending."""
        if not self._validate_candles(candles, self.range_lookback + 2):
            return None

        analysis = self.detector.detect(
            candles,
            lookback=self.range_lookback,
            tolerance=min(self.support_tolerance, self.resistance_tolerance),
            min_touches=self.min_range_touches,
        )

        if analysis.status != "ranging":
            return None

        # Filter out trending conditions using ADX
        adx = self._compute_adx(candles)
        if adx is None or adx >= self.adx_threshold:
            return None

        last = candles[-1]
        price = float(last.close)
        support = analysis.support
        resistance = analysis.resistance

        # LONG near support
        if price <= support * (1 + self.support_tolerance):
            strength = max(self.min_signal_strength, Decimal("0.6"))
            stop = Decimal(str(support * (1 - self.support_tolerance * 1.5)))
            take = Decimal(str(resistance))
            return Signal(
                pair=last.pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Range bounce LONG: price near support ({price:.2f} vs {support:.2f})",
                timestamp=last.timestamp,
                indicators={
                    "support": support,
                    "resistance": resistance,
                    "touches": analysis.touches,
                    "bandwidth_pct": analysis.bandwidth_pct,
                },
                stop_loss_price=stop,
                take_profit_price=take,
            )

        # SHORT near resistance
        if price >= resistance * (1 - self.resistance_tolerance):
            strength = max(self.min_signal_strength, Decimal("0.6"))
            stop = Decimal(str(resistance * (1 + self.resistance_tolerance * 1.5)))
            take = Decimal(str(support))
            return Signal(
                pair=last.pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Range rejection SHORT: price near resistance ({price:.2f} vs {resistance:.2f})",
                timestamp=last.timestamp,
                indicators={
                    "support": support,
                    "resistance": resistance,
                    "touches": analysis.touches,
                    "bandwidth_pct": analysis.bandwidth_pct,
                },
                stop_loss_price=stop,
                take_profit_price=take,
            )

        return None

    def _compute_adx(self, candles: List[Candle]) -> Optional[float]:
        """Compute ADX for trend strength filter."""
        import pandas as pd

        period = self.adx_period
        if len(candles) < period + 2:
            return None

        df = pd.DataFrame([
            {'high': float(c.high), 'low': float(c.low), 'close': float(c.close)}
            for c in candles[-(self.range_lookback + period + 5):]  # small buffer
        ])

        df['prev_close'] = df['close'].shift(1)
        df['tr'] = df.apply(
            lambda r: max(
                r['high'] - r['low'],
                abs(r['high'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
                abs(r['low'] - r['prev_close']) if pd.notna(r['prev_close']) else 0,
            ),
            axis=1,
        )
        df['plus_dm_raw'] = df['high'].diff()
        df['minus_dm_raw'] = -df['low'].diff()
        df['plus_dm'] = df.apply(
            lambda r: r['plus_dm_raw'] if (r['plus_dm_raw'] > r['minus_dm_raw']) and (r['plus_dm_raw'] > 0) else 0,
            axis=1,
        )
        df['minus_dm'] = df.apply(
            lambda r: r['minus_dm_raw'] if (r['minus_dm_raw'] > r['plus_dm_raw']) and (r['minus_dm_raw'] > 0) else 0,
            axis=1,
        )

        # Wilder smoothing
        def wilder_smooth(series):
            smoothed = series.ewm(alpha=1/period, adjust=False).mean()
            return smoothed

        tr_sm = wilder_smooth(df['tr'])
        plus_sm = wilder_smooth(df['plus_dm'])
        minus_sm = wilder_smooth(df['minus_dm'])

        plus_di = 100 * (plus_sm / tr_sm)
        minus_di = 100 * (minus_sm / tr_sm)
        dx = (abs(plus_di - minus_di) / (plus_di + minus_di)) * 100
        adx = dx.ewm(alpha=1/period, adjust=False).mean()

        latest_adx = float(adx.iloc[-1])
        return latest_adx
