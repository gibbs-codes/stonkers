"""Performance metrics for backtest results.

This module provides a `PerformanceAnalyzer` class that consumes a list of
executed trades (e.g., `BacktestTrade` from `src.engine.backtester`) plus an
optional equity curve and computes common trading metrics. The class is
pure/side‑effect free to keep it easy to unit test.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, DivisionByZero
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class TradeLike:
    """Minimal trade shape required by the analyzer."""

    pair: str
    strategy: str
    entry_time: any  # datetime
    exit_time: any  # datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    fees: Decimal


class PerformanceAnalyzer:
    """Compute core trading performance metrics for backtests.

    Metrics:
        - total_return_pct: (final_equity - initial) / initial * 100
        - sharpe_ratio: mean(period returns) / std(period returns) * sqrt(periods_per_year)
        - max_drawdown_pct: worst peak-to-trough decline from equity curve
        - win_rate_pct: winning trades / total trades * 100
        - avg_win: average P&L of winning trades
        - avg_loss: average P&L (absolute) of losing trades
        - avg_win_loss_ratio: avg_win / abs(avg_loss)
        - profit_factor: gross_profit / abs(gross_loss)
        - num_trades: count of trades
        - avg_hold_time: average duration of trades

    Edge cases:
        - If a metric is undefined (e.g., no losses for profit factor denominator),
          returns None instead of raising.
    """

    def __init__(self, periods_per_year: int = 252 * 24 * 4) -> None:
        """
        Args:
            periods_per_year: Scaling factor for Sharpe. Default assumes 15‑minute bars
                (252 trading days * 24h * 4 bars per hour). Override if you use
                different bar sizes or want daily Sharpe.
        """
        self.periods_per_year = periods_per_year

    def analyze(
        self,
        trades: Iterable[TradeLike],
        initial_equity: Decimal,
        equity_curve: Optional[List[Dict]] = None,
    ) -> Dict[str, Optional[Decimal]]:
        """Calculate metrics for a single strategy run."""
        trades_list = list(trades)
        num_trades = len(trades_list)

        # No trades: return empty-safe defaults
        if num_trades == 0:
            return {
                "total_return_pct": Decimal("0"),
                "sharpe_ratio": None,
                "max_drawdown_pct": None,
                "win_rate_pct": None,
                "avg_win": None,
                "avg_loss": None,
                "avg_win_loss_ratio": None,
                "profit_factor": None,
                "num_trades": 0,
                "avg_hold_time": None,
            }

        total_pnl = sum((t.pnl for t in trades_list), Decimal("0"))
        final_equity = initial_equity + total_pnl
        total_return_pct = (final_equity - initial_equity) / initial_equity * Decimal("100")

        # Wins / losses
        wins = [t.pnl for t in trades_list if t.pnl > 0]
        losses = [t.pnl for t in trades_list if t.pnl < 0]

        win_rate_pct = (Decimal(len(wins)) / Decimal(num_trades) * Decimal("100")) if num_trades else None
        avg_win = sum(wins, Decimal("0")) / Decimal(len(wins)) if wins else None
        avg_loss = sum(losses, Decimal("0")) / Decimal(len(losses)) if losses else None

        avg_win_loss_ratio = None
        if avg_win is not None and avg_loss is not None and avg_loss != 0:
            avg_win_loss_ratio = avg_win / abs(avg_loss)

        gross_profit = sum(wins, Decimal("0"))
        gross_loss = abs(sum(losses, Decimal("0")))  # positive value
        profit_factor = None
        if gross_loss > 0:
            profit_factor = gross_profit / gross_loss
        elif gross_profit > 0:
            profit_factor = Decimal("Infinity")

        avg_hold_time = self._average_hold_time(trades_list)

        sharpe_ratio = self._sharpe_ratio(trades_list, initial_equity, equity_curve)
        max_drawdown_pct = self._max_drawdown_pct(initial_equity, trades_list, equity_curve)

        return {
            "total_return_pct": total_return_pct,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown_pct": max_drawdown_pct,
            "win_rate_pct": win_rate_pct,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "avg_win_loss_ratio": avg_win_loss_ratio,
            "profit_factor": profit_factor,
            "num_trades": num_trades,
            "avg_hold_time": avg_hold_time,
        }

    # --------------------------------------------------------------------- compare
    def compare(self, results: Dict[str, Dict]) -> List[Dict]:
        """Rank multiple strategies by Sharpe ratio.

        Args:
            results: mapping strategy_name -> result dict containing at least
                `trades` and `initial_equity` (and optionally `equity_curve`).

        Returns:
            List of {strategy, metrics} sorted by Sharpe (desc, None last).
        """
        rows: List[Dict] = []
        for name, res in results.items():
            metrics = self.analyze(
                trades=res.get("trades", []),
                initial_equity=res.get("initial_equity", Decimal("0")),
                equity_curve=res.get("equity_curve"),
            )
            rows.append({"strategy": name, **metrics})

        rows.sort(key=lambda r: (Decimal("-Infinity") if r["sharpe_ratio"] is None else r["sharpe_ratio"]), reverse=True)
        return rows

    # -------------------------------------------------------------------- helpers
    def _average_hold_time(self, trades: List[TradeLike]) -> Optional[timedelta]:
        if not trades:
            return None
        durations = [(t.exit_time - t.entry_time) for t in trades]
        avg_seconds = sum((d.total_seconds() for d in durations), 0.0) / len(durations)
        return timedelta(seconds=avg_seconds)

    def _sharpe_ratio(
        self,
        trades: List[TradeLike],
        initial_equity: Decimal,
        equity_curve: Optional[List[Dict]] = None,
    ) -> Optional[Decimal]:
        """Compute Sharpe from an equity curve. Falls back to trade-level curve."""
        series = self._equity_series(initial_equity, trades, equity_curve)
        if len(series) < 2:
            return None

        # Period returns
        returns: List[Decimal] = []
        for prev, curr in zip(series[:-1], series[1:]):
            try:
                r = (curr - prev) / prev
            except DivisionByZero:
                continue
            returns.append(r)

        if not returns:
            return None

        mean_r = sum(returns, Decimal("0")) / Decimal(len(returns))
        # sample std
        if len(returns) < 2:
            return None
        variance = sum((r - mean_r) ** 2 for r in returns) / Decimal(len(returns) - 1)
        std_r = variance.sqrt() if variance >= 0 else None
        if not std_r or std_r == 0:
            return None

        annualized = mean_r / std_r * Decimal(math.sqrt(self.periods_per_year))
        return annualized

    def _max_drawdown_pct(
        self,
        initial_equity: Decimal,
        trades: List[TradeLike],
        equity_curve: Optional[List[Dict]] = None,
    ) -> Optional[Decimal]:
        series = self._equity_series(initial_equity, trades, equity_curve)
        if len(series) < 2:
            return None

        peak = series[0]
        max_dd = Decimal("0")
        for value in series[1:]:
            if value > peak:
                peak = value
            drawdown = (peak - value) / peak if peak else Decimal("0")
            if drawdown > max_dd:
                max_dd = drawdown
        return max_dd * Decimal("100")

    def _equity_series(
        self,
        initial_equity: Decimal,
        trades: List[TradeLike],
        equity_curve: Optional[List[Dict]] = None,
    ) -> List[Decimal]:
        """Return ordered equity series as Decimals."""
        if equity_curve:
            # assume sorted already
            return [Decimal(str(pt["equity"])) for pt in equity_curve]

        # Build stepwise equity from trades (ordered by exit time)
        equity = initial_equity
        series: List[Decimal] = [equity]
        for t in sorted(trades, key=lambda x: x.exit_time):
            equity += t.pnl
            series.append(equity)
        return series

