"""Generate an interactive HTML dashboard from fresh backtests."""
from __future__ import annotations

import json
import os
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import yaml
from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.models.candle import Candle
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.rsi_divergence import RsiDivergenceStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy
from src.strategies.range_trader import RangeTraderStrategy
from src.analysis.mtf_context import MtfContext


@dataclass
class StrategyResult:
    metrics: Dict
    trades: List[Dict]
    equity_curve: List[Dict]


def load_params(config_path: str) -> dict:
    path = Path(config_path)
    if not path.exists():
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def build_strategies(params: dict) -> List:
    return [
        EmaCrossoverStrategy(**(params.get("ema_cross") or {})),
        BollingerSqueezeStrategy(**(params.get("bb_squeeze") or {})),
        MomentumThrustStrategy(**(params.get("momentum_thrust") or {})),
        VwapMeanReversionStrategy(**(params.get("vwap_mean_rev") or {})),
        SupportResistanceBreakoutStrategy(**(params.get("support_resistance_breakout") or {})),
        RangeTraderStrategy(**(params.get("range_trader") or {})),
        EmaRsiStrategy(**(params.get("ema_rsi") or {})),
        RsiDivergenceStrategy(**(params.get("rsi_divergence") or {})),
    ]


def assign_mtf(strategies: List, raw_params: dict):
    mtf_tfs = set()
    for strat in strategies:
        cfg = raw_params.get(strat.name.lower(), {})
        strat.use_mtf_filter = cfg.get("use_mtf_filter", False)
        strat.mtf_timeframe = cfg.get("mtf_timeframe", "4h")
        if strat.use_mtf_filter:
            mtf_tfs.add(strat.mtf_timeframe)
    return list(mtf_tfs)


def fetch_candles(alpaca, pairs, timeframe, limit, days_back):
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=pairs, timeframe=timeframe, limit=limit, days_back=days_back
    )
    # trim to shortest to keep alignment simple
    min_len = min(len(v) for v in candles_by_pair.values() if v)
    for pair in list(candles_by_pair.keys()):
        candles_by_pair[pair] = candles_by_pair[pair][-min_len:]
    return candles_by_pair


def run_backtests(strategies, candles_by_pair, start, end, risk_manager, mtf_context=None) -> Dict[str, StrategyResult]:
    results = {}
    for strat in strategies:
        engine = BacktestEngine([strat], risk_manager, Decimal("1000"), mtf_context=mtf_context)
        metrics = engine.run(candles_by_pair, start, end)
        results[strat.name] = StrategyResult(metrics=metrics, trades=engine.trades, equity_curve=engine.equity_curve)
    return results


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


def calc_sortino(pnls: List[float]) -> float:
    if not pnls:
        return 0.0
    import math
    negatives = [p for p in pnls if p < 0]
    if not negatives:
        return float("inf")
    downside_std = (sum(p * p for p in negatives) / len(negatives)) ** 0.5
    avg = sum(pnls) / len(pnls)
    return 0.0 if downside_std == 0 else avg / downside_std


def calc_drawdown(equity_points: List[Dict]) -> Tuple[float, float, int]:
    max_equity = -1e9
    max_dd = 0.0
    current_dd = 0.0
    consec_losses = 0
    max_consec_losses = 0
    for point in equity_points:
        eq = float(point["equity"])
        if eq > max_equity:
            max_equity = eq
        drawdown = (max_equity - eq) / max_equity if max_equity > 0 else 0.0
        if drawdown > max_dd:
            max_dd = drawdown
        # simple consecutive loss proxy
        if drawdown > 0:
            consec_losses += 1
        else:
            max_consec_losses = max(max_consec_losses, consec_losses)
            consec_losses = 0
    max_consec_losses = max(max_consec_losses, consec_losses)
    return max_dd * 100, current_dd * 100, max_consec_losses


def build_equity_curves(results: Dict[str, StrategyResult]) -> Dict[str, List]:
    curves = {}
    for name, res in results.items():
        df = pd.DataFrame(res.equity_curve)
        if df.empty:
            continue
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df.sort_values("timestamp", inplace=True)
        curves[name] = df.to_dict(orient="list")
    return curves


def trades_to_df(trades: List[Dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame()
    df = pd.DataFrame(trades)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    df["hold_time"] = (df["exit_time"] - df["entry_time"]).dt.total_seconds() / 3600.0
    return df


def monthly_pnl(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    df["month"] = df["exit_time"].dt.to_period("M").astype(str)
    return df.groupby("month")["pnl"].sum()


def correlation_matrix(trade_dfs: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    # Build binary time series per strategy per entry bar (hour resolution)
    all_times = sorted(set(t for df in trade_dfs.values() for t in df["entry_time"].dt.floor("H").tolist())) if trade_dfs else []
    if not all_times:
        return pd.DataFrame()
    frame = pd.DataFrame(index=all_times)
    for name, df in trade_dfs.items():
        ts = df["entry_time"].dt.floor("H").value_counts().sort_index()
        frame[name] = ts
    frame.fillna(0, inplace=True)
    return frame.corr()


def color_scale(value, good_high=True):
    # simple green-red scale
    if value is None:
        return "#ccc"
    v = max(min(value, 1), -1)
    if good_high:
        g = int(200 + 55 * v)
        r = int(200 - 150 * v)
    else:
        g = int(200 - 150 * v)
        r = int(200 + 55 * v)
    return f"rgb({r},{g},180)"


def generate_html(results_on: Dict[str, StrategyResult], results_off: Dict[str, StrategyResult], out_path: Path):
    # Build data tables
    rows = []
    trade_dfs = {}
    for name, res in results_on.items():
        df = trades_to_df(res.trades)
        trade_dfs[name] = df
        sharpe = compute_sharpe(res.trades)
        max_dd, _, max_consec = calc_drawdown(res.equity_curve)
        rows.append({
            "strategy": name,
            "trades": res.metrics["total_trades"],
            "win_rate": res.metrics["win_rate"],
            "pnl": res.metrics["total_return_pct"],
            "pf": res.metrics["profit_factor"],
            "sharpe": sharpe,
            "max_dd": max_dd,
        })

    equity_curves = build_equity_curves(results_on)
    monthly = {name: monthly_pnl(trades_to_df(res.trades)).to_dict() for name, res in results_on.items()}
    corr = correlation_matrix({k: trades_to_df(v.trades) for k, v in results_on.items()})

    best_worst = {}
    for name, df in trade_dfs.items():
        if df.empty:
            best_worst[name] = {"best": [], "worst": []}
            continue
        best = df.nlargest(5, "pnl")[["pair", "entry_price", "exit_price", "pnl", "hold_time"]].to_dict(orient="records")
        worst = df.nsmallest(5, "pnl")[["pair", "entry_price", "exit_price", "pnl", "hold_time"]].to_dict(orient="records")
        best_worst[name] = {"best": best, "worst": worst}

    html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>Performance Dashboard</title>
  <script src="https://cdn.plot.ly/plotly-2.26.0.min.js"></script>
  <style>
    body {{ font-family: 'Helvetica Neue', sans-serif; margin: 20px; color: #222; }}
    h2 {{ margin-top: 32px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 12px; }}
    th, td {{ padding: 8px 10px; border: 1px solid #ddd; text-align: center; }}
    th {{ cursor: pointer; background: #f4f4f4; }}
  </style>
</head>
<body>
  <h1>Post-Backtest Performance Dashboard</h1>

  <h2>1. Strategy Comparison</h2>
  <table id="summary">
    <thead>
      <tr>
        <th>Strategy</th><th>Trades</th><th>Win%</th><th>P&L %</th><th>PF</th><th>Sharpe</th><th>Max DD%</th>
      </tr>
    </thead>
    <tbody>
      {''.join([f"<tr><td>{r['strategy']}</td><td>{r['trades']}</td><td>{r['win_rate']:.1f}</td><td>{r['pnl']:+.2f}</td><td>{r['pf']:.2f}</td><td>{r['sharpe']:.2f}</td><td>{r['max_dd']:.2f}</td></tr>" for r in rows])}
    </tbody>
  </table>

  <h2>2. Equity Curves</h2>
  <div id="equity" style="height:400px;"></div>

  <h2>3. Monthly Performance Heatmap</h2>
  <div id="heatmap" style="height:400px;"></div>

  <h2>4. Entry Correlation Matrix</h2>
  <div id="corr" style="height:400px;"></div>

  <h2>5. Best / Worst Trades</h2>
  <div id="bw"></div>

  <script>
    // Sorting
    document.querySelectorAll('#summary th').forEach((th, idx) => {{
      th.addEventListener('click', () => sortTable(idx));
    }});
    function sortTable(col) {{
      const table = document.getElementById('summary');
      let rows = Array.from(table.rows).slice(1);
      const dir = thDirs[col] = -(thDirs[col] || 1);
      rows.sort((a,b)=>dir*(parseFloat(a.cells[col].innerText)||a.cells[col].innerText.localeCompare(b.cells[col].innerText)));
      rows.forEach(r=>table.tBodies[0].appendChild(r));
    }}
    const thDirs = {{}};

    // Equity curves
    const equityData = {json.dumps(equity_curves)};
    const equityTraces = Object.entries(equityData).map(([name, d]) => ({{
      x: d.timestamp.map(t => new Date(t)),
      y: d.equity,
      name,
      mode: 'lines'
    }}));
    Plotly.newPlot('equity', equityTraces, {{yaxis: {{title:'Equity'}}, xaxis: {{title:'Time'}}}});

    // Monthly heatmap
    const monthly = {json.dumps(monthly)};
    const strategies = Object.keys(monthly);
    const months = Array.from(new Set([].concat(...Object.values(monthly).map(o=>Object.keys(o))))).sort();
    const z = strategies.map(s => months.map(m => monthly[s][m] || 0));
    Plotly.newPlot('heatmap', [{{
      z, x: months, y: strategies, type:'heatmap', colorscale:'RdYlGn', reversescale:true
    }}], {{xaxis: {{title:'Month'}}, yaxis: {{title:'Strategy'}}}});

    // Correlation
    const corr = {json.dumps(corr.to_dict() if not corr.empty else {})};
    if (Object.keys(corr).length) {{
      const strat = Object.keys(corr);
      const zc = strat.map(r => strat.map(c => corr[r][c]));
      Plotly.newPlot('corr', [{{
        z: zc, x: strat, y: strat, type:'heatmap', colorscale:'RdBu', zmid:0
      }}], {{xaxis:{{side:'top'}}, yaxis:{{autorange:'reversed'}}, title:'Entry correlation'}});
    }}

    // Best / worst trades
    const bwData = {json.dumps(best_worst)};
    let bwHtml = '';
    for (const [name, obj] of Object.entries(bwData)) {{
      bwHtml += `<h3>${{name}}</h3>`;
      ['best','worst'].forEach(side => {{
        bwHtml += `<h4>${{side === 'best' ? 'Top 5 Wins' : 'Top 5 Losses'}}</h4>`;
        bwHtml += '<table><tr><th>Pair</th><th>Entry</th><th>Exit</th><th>P&L</th><th>Hours</th></tr>';
        (obj[side]||[]).forEach(t => {{
          bwHtml += `<tr><td>${{t.pair}}</td><td>${{t.entry_price}}</td><td>${{t.exit_price}}</td><td>${{t.pnl.toFixed(2)}}</td><td>${{t.hold_time.toFixed(1)}}</td></tr>`;
        }});
        bwHtml += '</table>';
      }});
    }}
    document.getElementById('bw').innerHTML = bwHtml;
  </script>
</body>
</html>
"""
    out_path.write_text(html)


def main():
    load_dotenv(dotenv_path=".env", override=True)
    params_raw = load_params("config/strategy_params.yaml")
    params_clean = {}
    for k, v in params_raw.items():
        if isinstance(v, dict):
            params_clean[k] = {kk: vv for kk, vv in v.items() if kk not in ("use_mtf_filter", "mtf_timeframe")}
        else:
            params_clean[k] = v

    strategies = build_strategies(params_clean)
    mtf_timeframes = assign_mtf(strategies, params_raw)

    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    PAIRS = ["ETH/USD", "BTC/USD"]
    candles_by_pair = fetch_candles(
        alpaca,
        PAIRS,
        TimeFrame(15, TimeFrameUnit.Minute),
        limit=3000,
        days_back=35,
    )

    # date range
    all_ts = sorted({c.timestamp for cands in candles_by_pair.values() for c in cands})
    start_date, end_date = all_ts[0], all_ts[-1]

    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=Decimal("0.02"),
        take_profit_pct=Decimal("0.05"),
    )

    mtf_context = MtfContext(alpaca, PAIRS, mtf_timeframes)

    results_on = run_backtests(strategies, candles_by_pair, start_date, end_date, risk_manager, mtf_context)
    # Run again with filter off
    for s in strategies:
        s.use_mtf_filter = False
    results_off = run_backtests(strategies, candles_by_pair, start_date, end_date, risk_manager, None)

    generate_html(results_on, results_off, Path("analysis/performance_dashboard.html"))
    print("Dashboard written to analysis/performance_dashboard.html")


if __name__ == "__main__":
    main()
