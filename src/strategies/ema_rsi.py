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
        rsi_oversold: int = 30,
        rsi_overbought: int = 70,
        min_signal_strength: Decimal = Decimal("0.6"),
    ):
        """Initialize EMA + RSI strategy.

        Args:
            ema_period: Period for trend EMA (default 100)
            rsi_period: Period for RSI calculation (default 14)
            rsi_oversold: RSI oversold level (default 30)
            rsi_overbought: RSI overbought level (default 70)
            min_signal_strength: Minimum strength for signal (0.0-1.0)
        """
        super().__init__(name="EMA_RSI")
        self.ema_period = ema_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.min_signal_strength = min_signal_strength

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

        # Get latest values
        current = df.iloc[-1]
        previous = df.iloc[-2]

        current_price = current['close']
        current_rsi = current['rsi']
        previous_rsi = previous['rsi']
        ema = current['ema']

        # LONG signal: Price < EMA AND RSI crosses above oversold
        if current_price < ema and previous_rsi <= self.rsi_oversold < current_rsi:
            # Calculate signal strength based on distance from EMA
            distance_pct = abs((current_price - ema) / ema)
            # Closer to EMA = stronger signal (more likely to revert)
            strength = max(self.min_signal_strength, Decimal(str(1.0 - min(distance_pct, 0.4))))

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
                }
            )

        # SHORT signal: Price > EMA AND RSI crosses below overbought
        if current_price > ema and previous_rsi >= self.rsi_overbought > current_rsi:
            # Calculate signal strength based on distance from EMA
            distance_pct = abs((current_price - ema) / ema)
            strength = max(self.min_signal_strength, Decimal(str(1.0 - min(distance_pct, 0.4))))

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
