"""EMA + RSI Confluence Strategy.

Logic:
- LONG: Price < EMA (below trend) AND RSI crosses above oversold
- SHORT: Price > EMA (above trend) AND RSI crosses below overbought

This combines mean reversion (RSI extreme) with trend context (EMA position).
"""
from datetime import timezone
from decimal import Decimal
from typing import List, Optional

import pandas as pd

from src.models.candle import Candle
from src.models.signal import Signal, SignalType
from src.strategies.base import Strategy


class EmaRsiStrategy(Strategy):
    """EMA + RSI confluence strategy for mean reversion with trend context."""

    def __init__(
        self,
        ema_period: int = 100,
        rsi_period: int = 14,
        rsi_oversold: int = 38,
        rsi_overbought: int = 62,
        min_signal_strength: Decimal = Decimal("0.6"),
        max_distance_from_ema_pct: float = 0.06,
        min_distance_from_ema_pct: float = 0.0,  # NEW: minimum distance filter
        atr_period: int = 14,
        atr_multiplier_stop: float = 1.5,
        proximity_pct: float = 0.01,
    ):
        """Initialize EMA + RSI strategy.

        Args:
            ema_period: Period for trend EMA (default 100)
            rsi_period: Period for RSI calculation (default 14)
            rsi_oversold: RSI oversold level (default 38)
            rsi_overbought: RSI overbought level (default 62)
            min_signal_strength: Minimum strength for signal (0.0-1.0)
            max_distance_from_ema_pct: Skip trades if price is too far from EMA (default 6%)
            min_distance_from_ema_pct: Skip trades if price is too close to EMA (default 0%)
                                       Filters out noise when price is hugging EMA
            atr_period: ATR period (default 14)
            atr_multiplier_stop: ATR-based stop distance multiplier (default 1.5)
            proximity_pct: Max distance for entry signal (default 1%)
        """
        super().__init__(name="EMA_RSI")
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.min_signal_strength = (
            min_signal_strength
            if isinstance(min_signal_strength, Decimal)
            else Decimal(str(min_signal_strength))
        )
        self.max_distance_from_ema_pct = max_distance_from_ema_pct
        self.min_distance_from_ema_pct = min_distance_from_ema_pct
        self.atr_period = atr_period
        self.atr_multiplier_stop = atr_multiplier_stop
        self.proximity_pct = proximity_pct

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """Analyze candles for EMA + RSI confluence signals.

        Args:
            candles: List of recent candles (oldest first)

        Returns:
            Signal if entry conditions met, None otherwise
        """
        # Need enough candles for EMA calculation
        min_required = max(self.ema_period, self.rsi_period) + 2
        if not self._validate_candles(candles, min_required):
            return None

        # Convert to pandas DataFrame for TA calculations
        df = self._candles_to_df(candles)

        # Calculate EMA
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()

        # Calculate RSI
        df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)

        # Calculate ATR for dynamic stop sizing
        df['tr'] = self._calculate_true_range(df)
        df['atr'] = df['tr'].rolling(window=self.atr_period).mean()

        # Get latest values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_price = current['close']
        current_rsi = current['rsi']
        previous_rsi = previous['rsi']
        ema = current['ema']
        distance_pct = abs((current_price - ema) / ema)

        # Avoid catching extreme knives far from EMA
        if distance_pct > self.max_distance_from_ema_pct:
            return None

        # Skip entries too close to EMA — these are noise, not real dislocations
        # (Session 4 diagnostic: 0-0.2% distance had 25% win rate vs 75% at 0.6-0.8%)
        if distance_pct < self.min_distance_from_ema_pct:
            return None

        atr = current['atr']
        atr_stop = float(atr) * self.atr_multiplier_stop if not pd.isna(atr) else None

        # LONG signal: Price < EMA AND RSI crosses above oversold
        if current_price < ema and previous_rsi <= self.rsi_oversold < current_rsi and distance_pct <= self.proximity_pct:
            # Closer to EMA = stronger signal (more likely to revert)
            strength = max(self.min_signal_strength, Decimal(str(1.0 - min(distance_pct, 0.4))))
            stop_price = None
            if atr_stop is not None:
                stop_price = Decimal(str(max(0.0, float(current_price) - atr_stop)))
            take_profit = Decimal(str(ema))

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_LONG,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Price ${current_price:.2f} below EMA ${ema:.2f}, RSI crossed above {self.rsi_oversold} from {previous_rsi:.1f} to {current_rsi:.1f}",
                timestamp=candles[-1].timestamp,
                indicators={
                    'ema': float(ema),
                    'rsi': float(current_rsi),
                    'price': float(current_price),
                    'distance_from_ema_pct': float(distance_pct),
                    'atr': float(atr) if atr_stop is not None else None,
                    'atr_stop': atr_stop,
                },
                stop_loss_price=stop_price,
                take_profit_price=take_profit,
            )

        # SHORT signal: Price > EMA AND RSI crosses below overbought
        if current_price > ema and previous_rsi >= self.rsi_overbought > current_rsi and distance_pct <= self.proximity_pct:
            strength = max(self.min_signal_strength, Decimal(str(1.0 - min(distance_pct, 0.4))))
            stop_price = None
            if atr_stop is not None:
                stop_price = Decimal(str(float(current_price) + atr_stop))
            take_profit = Decimal(str(ema))

            return Signal(
                pair=candles[-1].pair,
                signal_type=SignalType.ENTRY_SHORT,
                strength=strength,
                strategy_name=self.name,
                reasoning=f"Price ${current_price:.2f} above EMA ${ema:.2f}, RSI crossed below {self.rsi_overbought} from {previous_rsi:.1f} to {current_rsi:.1f}",
                timestamp=candles[-1].timestamp,
                indicators={
                    'ema': float(ema),
                    'rsi': float(current_rsi),
                    'price': float(current_price),
                    'distance_from_ema_pct': float(distance_pct),
                    'atr': float(atr) if atr_stop is not None else None,
                    'atr_stop': atr_stop,
                },
                stop_loss_price=stop_price,
                take_profit_price=take_profit,
            )

        return None

    def diagnostics(self, candles: List[Candle]) -> dict:
        """Return current indicator values and condition statuses for debugging."""
        min_required = max(self.ema_period, self.rsi_period) + 2
        if not candles or len(candles) < min_required:
            return {"status": f"need {min_required} candles, have {len(candles) if candles else 0}"}

        df = self._candles_to_df(candles)
        df['ema'] = df['close'].ewm(span=self.ema_period, adjust=False).mean()
        df['rsi'] = self._calculate_rsi(df['close'], self.rsi_period)

        current = df.iloc[-1]
        previous = df.iloc[-2]
        price = current['close']
        ema = current['ema']
        rsi = current['rsi']
        prev_rsi = previous['rsi']
        distance_pct = abs((price - ema) / ema)

        side = "below" if price < ema else "above"
        rsi_cross_up = prev_rsi <= self.rsi_oversold < rsi
        rsi_cross_down = prev_rsi >= self.rsi_overbought > rsi

        return {
            "price": f"${price:.2f}",
            "ema": f"${ema:.2f} (price {side})",
            "distance": f"{distance_pct:.2%} (need <={self.proximity_pct:.0%})",
            "distance_filter": "PASS" if self.min_distance_from_ema_pct <= distance_pct <= self.max_distance_from_ema_pct else f"FAIL (need {self.min_distance_from_ema_pct:.1%}-{self.max_distance_from_ema_pct:.1%})",
            "proximity": "PASS" if distance_pct <= self.proximity_pct else "FAIL",
            "rsi": f"{rsi:.1f} (prev {prev_rsi:.1f})",
            "rsi_long": f"{'PASS' if rsi_cross_up else 'FAIL'} (need prev<={self.rsi_oversold}, curr>{self.rsi_oversold})",
            "rsi_short": f"{'PASS' if rsi_cross_down else 'FAIL'} (need prev>={self.rsi_overbought}, curr<{self.rsi_overbought})",
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
                'timestamp': c.timestamp,
                'open': float(c.open),
                'high': float(c.high),
                'low': float(c.low),
                'close': float(c.close),
                'volume': float(c.volume),
            }
            for c in candles
        ])

    def _calculate_rsi(self, prices: pd.Series, period: int) -> pd.Series:
        """Calculate RSI indicator.

        Args:
            prices: Series of closing prices
            period: RSI period

        Returns:
            Series of RSI values
        """
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_true_range(self, df: pd.DataFrame) -> pd.Series:
        """Calculate True Range for ATR."""
        prev_close = df['close'].shift(1)
        tr1 = df['high'] - df['low']
        tr2 = (df['high'] - prev_close).abs()
        tr3 = (df['low'] - prev_close).abs()
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr
