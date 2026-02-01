"""Parameter sweep for EMA+RSI strategy.

Grid:
- rsi_oversold: [45, 50, 55]
- min_distance_from_ema_pct: [0.004, 0.006, 0.008]
- stop_loss_pct (RiskManager): [0.015, 0.020, 0.025]

Ranks by Sharpe (primary), Win Rate (secondary), Max DD (tertiary).
Outputs top-5 results to analysis/parameter_sweep_results.md
"""
from __future__ import annotations

import itertools
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml
from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# Ensure repo root on path
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.analysis.mtf_context import MtfContext
from src.strategies.ema_rsi import EmaRsiStrategy
import src.engine.backtest as be


@dataclass
class SweepResult:
    params: Dict
    stop_loss_pct: float
    metrics: Dict
    sharpe: float


def compute_sharpe(trades: List[Dict]) -> float:
    if not trades or len(trades) < 2:
        return 0.0
    pnls = [t["pnl"] for t in trades]
    if len(pnls) < 2:
        return 0.0
    import statistics
    mean = statistics.mean(pnls)
    std = statistics.stdev(pnls)
    return 0.0 if std == 0 else mean / std


def fetch_base_data(pairs, days_back=35, limit=3000):
    load_dotenv(dotenv_path=".env", override=True)
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=pairs,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=limit,
        days_back=days_back,
    )
    min_len = min(len(v) for v in candles_by_pair.values() if v)
    for pair in list(candles_by_pair.keys()):
        candles_by_pair[pair] = candles_by_pair[pair][-min_len:]
    all_ts = sorted({c.timestamp for cands in candles_by_pair.values() for c in cands})
    start_date, end_date = all_ts[0], all_ts[-1]
    return alpaca, candles_by_pair, start_date, end_date


def main():
    pairs = ["BTC/USD"]  # single pair to keep sweep fast/stable
    # mute console output for speed
    be.console.print = lambda *a, **k: None
    alpaca, candles_by_pair, start_date, end_date = fetch_base_data(pairs)

    # MTF context (4h) for consistency with config
    mtf_context = MtfContext(alpaca, pairs, ["4h"])

    grid = {
        "rsi_oversold": [45, 50, 55],
        "min_distance_from_ema_pct": [0.004, 0.006, 0.008],
        "stop_loss_pct": [0.015, 0.020, 0.025],
    }

    combos = list(itertools.product(
        grid["rsi_oversold"],
        grid["min_distance_from_ema_pct"],
        grid["stop_loss_pct"],
    ))

    results: List[SweepResult] = []

    for rsi_over, dist, sl in combos:
        params = {
            "rsi_oversold": rsi_over,
            "rsi_overbought": 57,  # keep from base config
            "min_signal_strength": 0.65,
            "max_distance_from_ema_pct": 0.05,
            "min_distance_from_ema_pct": dist,
            "atr_period": 14,
            "atr_multiplier_stop": 1.5,
            "proximity_pct": 0.01,
        }

        strat = EmaRsiStrategy(**params)
        strat.use_mtf_filter = True
        strat.mtf_timeframe = "4h"

        risk_manager = RiskManager(
            max_positions=5,
            max_position_size_pct=Decimal("0.2"),
            stop_loss_pct=Decimal(str(sl)),
            take_profit_pct=Decimal("0.05"),
        )

        engine = BacktestEngine([strat], risk_manager, Decimal("1000"), mtf_context=mtf_context)
        metrics = engine.run(candles_by_pair, start_date, end_date)
        sharpe = compute_sharpe(engine.trades)

        results.append(SweepResult(params=params, stop_loss_pct=sl, metrics=metrics, sharpe=sharpe))

    # rank: sharpe desc, win_rate desc, max_dd asc
    results.sort(key=lambda r: (
        -r.sharpe,
        -r.metrics["win_rate"],
        r.metrics["max_drawdown"],
    ))

    top5 = results[:5]

    lines = []
    lines.append("# EMA+RSI Parameter Sweep (15m, 30 days, pairs: ETH/USD & BTC/USD)")
    lines.append("Warning: Candidate settings only. Validate on fresh data before using.")
    lines.append("")
    lines.append("| Rank | rsi_oversold | min_dist_ema_pct | stop_loss_pct | Trades | Win% | P&L% | PF | Sharpe | Max DD% |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for i, res in enumerate(top5, 1):
        m = res.metrics
        lines.append(
            f"| {i} | {res.params['rsi_oversold']} | {res.params['min_distance_from_ema_pct']:.3f} | "
            f"{res.stop_loss_pct:.3f} | {m['total_trades']} | {m['win_rate']:.1f}% | {m['total_return_pct']:+.2f}% | "
            f"{m['profit_factor']:.2f} | {res.sharpe:.2f} | {m['max_drawdown']:.2f}% |"
        )

    out = Path("analysis/parameter_sweep_results.md")
    out.write_text("\n".join(lines))
    print("Wrote", out)


if __name__ == "__main__":
    main()
