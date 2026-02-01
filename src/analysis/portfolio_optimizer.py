"""Portfolio optimizer across strategies.

Builds candidate allocations (equal, performance-weighted, Sharpe-weighted with correlation tilt),
backtests each strategy individually, then combines daily returns to estimate portfolio metrics.
Outputs recommendation to analysis/portfolio_optimizer.md.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import yaml
from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

# repo root
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.analysis.mtf_context import MtfContext
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.rsi_divergence import RsiDivergenceStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy
from src.strategies.range_trader import RangeTraderStrategy


def load_params(path="config/strategy_params.yaml"):
    with open(path) as f:
        return yaml.safe_load(f) or {}


def build_strategies(params: dict):
    return {
        "BB_SQUEEZE": BollingerSqueezeStrategy(**(params.get("bb_squeeze") or {})),
        "EMA_CROSS": EmaCrossoverStrategy(**(params.get("ema_cross") or {})),
        "EMA+RSI": EmaRsiStrategy(**(params.get("ema_rsi") or {})),
        "MOMENTUM_THRUST": MomentumThrustStrategy(**(params.get("momentum_thrust") or {})),
        "RSI_DIV": RsiDivergenceStrategy(**(params.get("rsi_divergence") or {})),
        "VWAP_MEAN_REV": VwapMeanReversionStrategy(**(params.get("vwap_mean_rev") or {})),
        "SR_BREAKOUT": SupportResistanceBreakoutStrategy(**(params.get("support_resistance_breakout") or {})),
        "RANGE_TRADER": RangeTraderStrategy(**(params.get("range_trader") or {})),
    }


def apply_mtf(strategies: Dict[str, object], raw_params: dict):
    mtfs = set()
    for s in strategies.values():
        cfg = raw_params.get(s.name.lower(), {})
        s.use_mtf_filter = cfg.get("use_mtf_filter", False)
        s.mtf_timeframe = cfg.get("mtf_timeframe", "4h")
        if s.use_mtf_filter:
            mtfs.add(s.mtf_timeframe)
    return list(mtfs)


def fetch_candles(alpaca, pairs, limit=3000, days_back=35):
    candles = alpaca.fetch_recent_candles(
        pairs=pairs,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=limit,
        days_back=days_back,
    )
    min_len = min(len(v) for v in candles.values() if v)
    for k in list(candles.keys()):
        candles[k] = candles[k][-min_len:]
    ts = sorted({c.timestamp for v in candles.values() for c in v})
    return candles, ts[0], ts[-1]


def sharpe(daily_returns: pd.Series):
    if len(daily_returns) < 2:
        return 0.0
    return daily_returns.mean() / (daily_returns.std() + 1e-9)


def equity_from_returns(daily_returns: pd.Series, start_equity=1000):
    equity = (1 + daily_returns).cumprod() * start_equity
    dd = (equity.cummax() - equity) / equity.cummax()
    return equity, dd.max()


def build_daily_returns(trades: List[Dict], start_equity=1000) -> pd.Series:
    if not trades:
        return pd.Series(dtype=float)
    df = pd.DataFrame(trades)
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    daily = df.groupby(df["exit_time"].dt.date)["pnl"].sum() / start_equity
    daily.index = pd.to_datetime(daily.index)
    return daily.sort_index()


def make_portfolios(strategy_metrics: Dict[str, Dict], daily_returns: Dict[str, pd.Series]):
    names = list(strategy_metrics.keys())
    n = len(names)
    equal_w = np.array([1 / n] * n)

    # performance weight by total pnl (positive only)
    pnl = np.array([strategy_metrics[k]["pnl"] for k in names])
    perf_w = np.maximum(pnl, 0)
    perf_w = perf_w / perf_w.sum() if perf_w.sum() > 0 else equal_w

    # sharpe weight
    sh = np.array([strategy_metrics[k]["sharpe"] for k in names])
    sh_pos = np.maximum(sh, 0)
    sharpe_w = sh_pos / sh_pos.sum() if sh_pos.sum() > 0 else equal_w

    # correlation adjustment on sharpe weights
    # build aligned daily return frame
    all_idx = sorted(set().union(*[dr.index for dr in daily_returns.values()]))
    frame = pd.DataFrame(index=all_idx)
    for k, dr in daily_returns.items():
        frame[k] = dr
    frame.fillna(0, inplace=True)
    corr = frame.corr().fillna(0)
    corr_penalty = np.maximum(0, corr.values - 0.6)  # penalize >0.6
    corr_factor = 1 - corr_penalty.mean(axis=1)
    corr_factor = np.clip(corr_factor, 0.2, 1.0)
    corr_weight = sharpe_w * corr_factor
    corr_weight = corr_weight / corr_weight.sum()

    portfolios = {
        "Equal": equal_w,
        "Performance": perf_w,
        "Sharpe": sharpe_w,
        "SharpeCorr": corr_weight,
    }
    return portfolios, names, frame


def eval_portfolio(weights: np.ndarray, names: List[str], frame: pd.DataFrame, start_equity=1000):
    w_series = pd.Series(weights, index=names)
    port_daily = frame.mul(w_series, axis=1).sum(axis=1)
    equity, max_dd = equity_from_returns(port_daily, start_equity)
    pf = port_daily[port_daily > 0].sum() / abs(port_daily[port_daily <= 0].sum() + 1e-9) if not port_daily.empty else 0
    return {
        "daily": port_daily,
        "equity": equity,
        "max_dd": float(max_dd * 100),
        "sharpe": float(sharpe(port_daily)),
        "pf": float(pf),
        "pnl_pct": float((equity.iloc[-1] - start_equity) / start_equity * 100) if not equity.empty else 0,
    }


def main():
    load_dotenv(dotenv_path=".env", override=True)
    raw_params = load_params()
    params_clean = {k: {kk: vv for kk, vv in v.items() if kk not in ("use_mtf_filter", "mtf_timeframe")} for k, v in raw_params.items() if isinstance(v, dict)}

    strategies = build_strategies(params_clean)
    mtf_tfs = apply_mtf(strategies, raw_params)

    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    PAIRS = ["ETH/USD", "BTC/USD"]
    candles, start_date, end_date = fetch_candles(alpaca, PAIRS)
    mtf_context = MtfContext(alpaca, PAIRS, mtf_tfs)

    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=Decimal("0.02"),
        take_profit_pct=Decimal("0.05"),
    )

    results = {}
    daily_returns = {}
    strategy_metrics = {}
    for name, strat in strategies.items():
        engine = BacktestEngine([strat], risk_manager, Decimal("1000"), mtf_context=mtf_context)
        m = engine.run(candles, start_date, end_date)
        results[name] = m
        daily_returns[name] = build_daily_returns(engine.trades)
        strategy_metrics[name] = {
            "pnl": m["total_return"],
            "sharpe": float(sharpe(daily_returns[name])),
        }

    portfolios, names, frame = make_portfolios(strategy_metrics, daily_returns)
    portfolio_stats = {}
    for pname, w in portfolios.items():
        portfolio_stats[pname] = eval_portfolio(w, names, frame)

    # choose best by sharpe then max_dd
    best = sorted(portfolio_stats.items(), key=lambda kv: (-kv[1]["sharpe"], kv[1]["max_dd"]))[0][0]

    lines = []
    lines.append("# Strategy Portfolio Optimization")
    lines.append(f"Period: {start_date.date()} to {end_date.date()} (15m, pairs: ETH/USD, BTC/USD)")
    lines.append("")
    lines.append("## Individual Strategies")
    lines.append("| Strategy | Trades | Win% | P&L% | PF | Sharpe |")
    lines.append("|---|---|---|---|---|---|")
    for n in names:
        m = results[n]
        lines.append(f"| {n} | {m['total_trades']} | {m['win_rate']:.1f}% | {m['total_return_pct']:+.2f}% | {m['profit_factor']:.2f} | {strategy_metrics[n]['sharpe']:.2f} |")

    lines.append("\n## Portfolios")
    lines.append("| Portfolio | Weights | Sharpe | PF | Max DD% | P&L% |")
    lines.append("|---|---|---|---|---|---|")
    for pname, w in portfolios.items():
        weight_str = ", ".join(f"{n}:{w[i]:.2f}" for i, n in enumerate(names) if w[i] > 0.01)
        ps = portfolio_stats[pname]
        lines.append(f"| {pname} | {weight_str} | {ps['sharpe']:.2f} | {ps['pf']:.2f} | {ps['max_dd']:.2f}% | {ps['pnl_pct']:+.2f}% |")

    lines.append(f"\n**Recommended portfolio:** {best} (highest Sharpe with lower drawdown among candidates)")

    out = Path("analysis/portfolio_optimizer.md")
    out.write_text("\n".join(lines))
    print("Wrote", out)


if __name__ == "__main__":
    main()
