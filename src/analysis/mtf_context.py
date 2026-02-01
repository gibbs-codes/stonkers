"""Multi-timeframe context helper for higher-timeframe trend filtering."""
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Dict, List

import pandas as pd

from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.models.candle import Candle


class MtfContext:
    """Precomputes HTF candles and 200 EMA to supply trend direction."""

    def __init__(self, alpaca_connector, pairs: List[str], timeframes: List[str], limit: int = 400):
        self.data: Dict[str, Dict[str, pd.DataFrame]] = defaultdict(dict)
        self._build(alpaca_connector, pairs, timeframes, limit)

    def _tf_to_timeframe(self, tf: str) -> TimeFrame:
        tf = tf.lower()
        if tf.endswith("h"):
            hours = int(tf.replace("h", ""))
            return TimeFrame(hours, TimeFrameUnit.Hour)
        if tf.endswith("d"):
            days = int(tf.replace("d", ""))
            return TimeFrame(days, TimeFrameUnit.Day)
        if tf.endswith("m"):
            mins = int(tf.replace("m", ""))
            return TimeFrame(mins, TimeFrameUnit.Minute)
        raise ValueError(f"Unsupported timeframe: {tf}")

    def _build(self, alpaca, pairs: List[str], timeframes: List[str], limit: int):
        unique_tfs = sorted(set(timeframes))
        for tf in unique_tfs:
            tf_obj = self._tf_to_timeframe(tf)
            candles_by_pair = alpaca.fetch_recent_candles(
                pairs=pairs,
                timeframe=tf_obj,
                limit=limit,
            )
            for pair, candles in candles_by_pair.items():
                if not candles:
                    continue
                df = pd.DataFrame([{
                    "timestamp": c.timestamp,
                    "close": float(c.close),
                } for c in candles])
                df.sort_values("timestamp", inplace=True)
                df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
                self.data[tf][pair] = df

    def get_trend(self, pair: str, timestamp: datetime, timeframe: str = "4h") -> str:
        """Return bullish / bearish / neutral relative to 200 EMA at given time."""
        tf = timeframe.lower()
        if tf not in self.data or pair not in self.data[tf]:
            return "neutral"
        df = self.data[tf][pair]
        # find last candle at or before timestamp
        df = df[df["timestamp"] <= timestamp]
        if df.empty:
            return "neutral"
        row = df.iloc[-1]
        if pd.isna(row["ema200"]):
            return "neutral"
        if row["close"] > row["ema200"]:
            return "bullish"
        if row["close"] < row["ema200"]:
            return "bearish"
        return "neutral"
