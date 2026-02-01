"""Range detection helper for sideways vs trending markets."""
from dataclasses import dataclass
from typing import List

import pandas as pd

from src.models.candle import Candle


@dataclass
class RangeAnalysis:
    """Result of a range/trend classification."""
    status: str  # "ranging", "trending", or "insufficient"
    support: float
    resistance: float
    touches: int
    support_touches: int
    resistance_touches: int
    bandwidth_pct: float


class RangeDetector:
    """Detect whether price is ranging or trending using swing extremes."""

    def detect(
        self,
        candles: List[Candle],
        lookback: int = 20,
        tolerance: float = 0.005,
        min_touches: int = 3,
    ) -> RangeAnalysis:
        """Classify current state and return S/R levels.

        Args:
            candles: List of candles (oldest first)
            lookback: Candles to scan for support/resistance
            tolerance: Proximity % to count a touch (e.g., 0.005 = 0.5%)
            min_touches: Min total boundary touches to call it a range
        """
        if len(candles) < lookback:
            return RangeAnalysis("insufficient", 0, 0, 0, 0, 0, 0)

        df = pd.DataFrame([
            {'high': float(c.high), 'low': float(c.low), 'close': float(c.close)}
            for c in candles[-lookback:]
        ])

        support = df['low'].min()
        resistance = df['high'].max()
        bandwidth_pct = (resistance - support) / support if support != 0 else 0

        # Count touches near boundaries
        sup_thresh = support * (1 + tolerance)
        res_thresh = resistance * (1 - tolerance)
        support_touches = (df['close'] <= sup_thresh).sum()
        resistance_touches = (df['close'] >= res_thresh).sum()
        touches = int(support_touches + resistance_touches)

        # Trending test: current price breaking out of range
        current_close = df['close'].iloc[-1]
        trending_up = current_close > resistance * (1 + tolerance)
        trending_down = current_close < support * (1 - tolerance)
        status = "trending" if (trending_up or trending_down) else "ranging"

        # Require minimum touches on boundaries to confirm range
        if status == "ranging" and (touches < min_touches or support_touches == 0 or resistance_touches == 0):
            status = "insufficient"

        return RangeAnalysis(
            status=status,
            support=float(support),
            resistance=float(resistance),
            touches=touches,
            support_touches=int(support_touches),
            resistance_touches=int(resistance_touches),
            bandwidth_pct=float(bandwidth_pct),
        )
