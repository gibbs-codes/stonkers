"""RSI Divergence Strategy."""
import pandas as pd
import ta
import numpy as np
from typing import Optional, List
from src.strategies.base import Strategy
from src.data.models import Candle, Signal, Direction


class RsiDivergenceStrategy(Strategy):
    """
    RSI Divergence Strategy.

    Logic:
    - Bullish divergence: Price makes lower low, RSI makes higher low
    - Bearish divergence: Price makes higher high, RSI makes lower high
    - Exit: RSI reaches opposite extreme
    """

    name = "rsi_divergence"
    description = "RSI divergence reversal strategy"
    required_history = 50

    def configure(self, params: dict) -> None:
        """Configure strategy parameters."""
        defaults = self.get_default_params()
        self.params = {**defaults, **params}

    def get_default_params(self) -> dict:
        """Return default parameters."""
        return {
            'rsi_period': 14,
            'lookback': 10
        }

    def _find_peaks_and_troughs(self, series: pd.Series, lookback: int) -> dict:
        """
        Find local peaks and troughs in a series.

        Args:
            series: Price or indicator series
            lookback: Number of periods to look back

        Returns:
            Dict with 'peaks' and 'troughs' indices
        """
        peaks = []
        troughs = []

        for i in range(lookback, len(series) - lookback):
            # Check if it's a peak
            if series.iloc[i] == series.iloc[i-lookback:i+lookback+1].max():
                peaks.append(i)
            # Check if it's a trough
            if series.iloc[i] == series.iloc[i-lookback:i+lookback+1].min():
                troughs.append(i)

        return {'peaks': peaks, 'troughs': troughs}

    def analyze(self, candles: List[Candle]) -> Optional[Signal]:
        """
        Analyze candles and generate signal.

        Args:
            candles: List of historical candles (newest last)

        Returns:
            Signal object if conditions met, None otherwise
        """
        if not self.validate_candles(candles):
            return None

        # Convert to DataFrame
        df = pd.DataFrame([
            {'timestamp': c.timestamp, 'close': c.close, 'low': c.low, 'high': c.high}
            for c in candles
        ])

        # Calculate RSI
        rsi_period = self.params['rsi_period']
        df['rsi'] = ta.momentum.rsi(df['close'], window=rsi_period)

        lookback = self.params['lookback']

        # Find peaks and troughs in price and RSI
        price_extremes = self._find_peaks_and_troughs(df['close'], lookback)
        rsi_extremes = self._find_peaks_and_troughs(df['rsi'], lookback)

        current_candle = candles[-1]
        current_price = df['close'].iloc[-1]
        current_rsi = df['rsi'].iloc[-1]

        # Check for BULLISH divergence
        # Need at least 2 troughs
        if len(price_extremes['troughs']) >= 2 and len(rsi_extremes['troughs']) >= 2:
            # Get last two troughs
            price_trough_1 = price_extremes['troughs'][-2]
            price_trough_2 = price_extremes['troughs'][-1]
            rsi_trough_1 = rsi_extremes['troughs'][-2]
            rsi_trough_2 = rsi_extremes['troughs'][-1]

            # Bullish divergence: price lower low, RSI higher low
            if (df['close'].iloc[price_trough_2] < df['close'].iloc[price_trough_1] and
                df['rsi'].iloc[rsi_trough_2] > df['rsi'].iloc[rsi_trough_1]):

                reasoning = (
                    f"LONG signal: Bullish divergence detected. "
                    f"Price made lower low ({df['close'].iloc[price_trough_1]:.2f} → "
                    f"{df['close'].iloc[price_trough_2]:.2f}) "
                    f"while RSI made higher low ({df['rsi'].iloc[rsi_trough_1]:.2f} → "
                    f"{df['rsi'].iloc[rsi_trough_2]:.2f}). "
                    f"Current price: {current_price:.2f}, RSI: {current_rsi:.2f}. "
                    f"This suggests weakening downside momentum."
                )

                return Signal(
                    timestamp=current_candle.timestamp,
                    pair=current_candle.pair,
                    direction=Direction.LONG,
                    strength=0.8,
                    strategy_name=self.name,
                    reasoning=reasoning,
                    indicators={
                        'price': current_price,
                        'rsi': current_rsi,
                        'price_trough_1': df['close'].iloc[price_trough_1],
                        'price_trough_2': df['close'].iloc[price_trough_2],
                        'rsi_trough_1': df['rsi'].iloc[rsi_trough_1],
                        'rsi_trough_2': df['rsi'].iloc[rsi_trough_2]
                    },
                    timeframe=current_candle.timeframe
                )

        # Check for BEARISH divergence
        # Need at least 2 peaks
        if len(price_extremes['peaks']) >= 2 and len(rsi_extremes['peaks']) >= 2:
            # Get last two peaks
            price_peak_1 = price_extremes['peaks'][-2]
            price_peak_2 = price_extremes['peaks'][-1]
            rsi_peak_1 = rsi_extremes['peaks'][-2]
            rsi_peak_2 = rsi_extremes['peaks'][-1]

            # Bearish divergence: price higher high, RSI lower high
            if (df['close'].iloc[price_peak_2] > df['close'].iloc[price_peak_1] and
                df['rsi'].iloc[rsi_peak_2] < df['rsi'].iloc[rsi_peak_1]):

                reasoning = (
                    f"SHORT signal: Bearish divergence detected. "
                    f"Price made higher high ({df['close'].iloc[price_peak_1]:.2f} → "
                    f"{df['close'].iloc[price_peak_2]:.2f}) "
                    f"while RSI made lower high ({df['rsi'].iloc[rsi_peak_1]:.2f} → "
                    f"{df['rsi'].iloc[rsi_peak_2]:.2f}). "
                    f"Current price: {current_price:.2f}, RSI: {current_rsi:.2f}. "
                    f"This suggests weakening upside momentum."
                )

                return Signal(
                    timestamp=current_candle.timestamp,
                    pair=current_candle.pair,
                    direction=Direction.SHORT,
                    strength=0.8,
                    strategy_name=self.name,
                    reasoning=reasoning,
                    indicators={
                        'price': current_price,
                        'rsi': current_rsi,
                        'price_peak_1': df['close'].iloc[price_peak_1],
                        'price_peak_2': df['close'].iloc[price_peak_2],
                        'rsi_peak_1': df['rsi'].iloc[rsi_peak_1],
                        'rsi_peak_2': df['rsi'].iloc[rsi_peak_2]
                    },
                    timeframe=current_candle.timeframe
                )

        return None
