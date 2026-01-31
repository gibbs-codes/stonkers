"""Parameter sweep for BB_SQUEEZE — the best-performing strategy.

First sweep (18 combos) proved that squeeze_threshold and min_signal_strength
are inert on 15-min crypto data: every breakout already clears the
RiskManager's 0.4 strength floor, and squeezes appear everywhere in a 10-bar
lookback.  The ONLY axis that changed trade outcomes was stop_loss_pct.

This version sweeps the two axes that actually matter:
    stop_loss_pct   – how far price can move against us before we cut
    take_profit_pct – how far price must move for us before we take

3 stops × 3 take-profits = 9 unique combos.  squeeze_threshold and
min_signal_strength are held at their defaults (0.04, 0.6).

Results ranked by (win_rate, profit_factor, total_return) and the top 3
written to config/tuned_params.yaml.
"""

import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Dict, List

import yaml
from rich.console import Console

# ---------------------------------------------------------------------------
# Suppress BacktestEngine's own rich output during sweeps by monkey-patching
# the module-level console it uses.  We restore it after.
# ---------------------------------------------------------------------------
import src.engine.backtest as _bt_mod

_real_console = _bt_mod.console
_null_console = Console(file=StringIO())  # output goes to /dev/null


from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy

console = Console()
load_dotenv()

# ---------------------------------------------------------------------------
# Sweep grid  (only the two axes that actually reshape trade outcomes)
# ---------------------------------------------------------------------------
# stop_loss_pct: tighter = smaller losses, but more frequent early exits
STOP_LOSSES = [Decimal("0.01"), Decimal("0.015"), Decimal("0.02")]   # 1%, 1.5%, 2%

# take_profit_pct: higher = let winners run further, but fewer will reach it
TAKE_PROFITS = [Decimal("0.03"), Decimal("0.05"), Decimal("0.07")]   # 3%, 5%, 7%

# Fixed — proven inert on this data in sweep 1
SQUEEZE_THRESHOLD = 0.04
MIN_SIGNAL_STRENGTH = Decimal("0.6")

PAIRS = ["ETH/USD", "SOL/USD"]
DAYS_BACK = 30
INITIAL_BALANCE = Decimal("1000")


def fetch_candles() -> Dict[str, list]:
    """Download 30 days of 15-min candles once, reuse for all sweep runs."""
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )
    return alpaca.fetch_recent_candles(
        pairs=PAIRS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=3000,
    )


def run_single(
    candles_by_pair: dict,
    start_date: datetime,
    end_date: datetime,
    stop_loss_pct: Decimal,
    take_profit_pct: Decimal,
) -> Dict:
    """Run one backtest combo silently and return its metrics dict."""
    strategy = BollingerSqueezeStrategy(
        squeeze_threshold=SQUEEZE_THRESHOLD,
        min_signal_strength=MIN_SIGNAL_STRENGTH,
    )
    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
    )

    # Silence the engine's own printing
    _bt_mod.console = _null_console
    try:
        engine = BacktestEngine([strategy], risk_manager, INITIAL_BALANCE)
        metrics = engine.run(candles_by_pair, start_date, end_date)
    finally:
        _bt_mod.console = _real_console

    # Attach the params we swept so we can write them out later
    metrics["_params"] = {
        "squeeze_threshold": SQUEEZE_THRESHOLD,
        "min_signal_strength": float(MIN_SIGNAL_STRENGTH),
        "stop_loss_pct": float(stop_loss_pct),
        "take_profit_pct": float(take_profit_pct),
    }
    return metrics


def main():
    total_combos = len(STOP_LOSSES) * len(TAKE_PROFITS)

    console.print("\n[bold cyan]══════════════════════════════════════════════[/bold cyan]")
    console.print(f"[bold cyan]   BB_SQUEEZE PARAMETER SWEEP ({total_combos} combos)[/bold cyan]")
    console.print("[bold cyan]══════════════════════════════════════════════[/bold cyan]\n")
    console.print(f"[dim]Fixed: squeeze_threshold={SQUEEZE_THRESHOLD}, "
                  f"min_signal_strength={MIN_SIGNAL_STRENGTH}[/dim]")
    console.print(f"[dim]Sweep: stop_loss_pct × take_profit_pct[/dim]\n")

    # --- fetch data once ---
    console.print("[bold]Downloading candle data...[/bold]")
    candles_by_pair = fetch_candles()
    for pair, candles in candles_by_pair.items():
        console.print(f"  {pair}: {len(candles)} candles")
    console.print()

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_BACK)

    # --- run sweep ---
    results: List[Dict] = []
    combo_num = 0

    for sl_pct in STOP_LOSSES:
        for tp_pct in TAKE_PROFITS:
            combo_num += 1
            console.print(
                f"  [{combo_num:>2}/{total_combos}] "
                f"stop={float(sl_pct)*100:.1f}%  take={float(tp_pct)*100:.1f}%",
                end=" "
            )

            metrics = run_single(
                candles_by_pair, start_date, end_date,
                sl_pct, tp_pct,
            )
            results.append(metrics)

            console.print(
                f"→ trades={metrics['total_trades']:>2}  "
                f"wr={metrics['win_rate']:>5.1f}%  "
                f"pf={metrics['profit_factor']:>4.2f}  "
                f"ret=${metrics['total_return']:>+7.2f}"
            )

    # --- rank & display ---
    ranked = [r for r in results if r["total_trades"] > 0]
    # Primary: win_rate. Tiebreak: profit_factor, then total_return.
    ranked.sort(key=lambda r: (r["win_rate"], r["profit_factor"], r["total_return"]), reverse=True)

    console.print("\n[bold green]══════════════════════════════════════════════[/bold green]")
    console.print("[bold green]   RANKED RESULTS (all shown)[/bold green]")
    console.print("[bold green]══════════════════════════════════════════════[/bold green]\n")

    from rich.table import Table
    table = Table(show_header=True)
    table.add_column("Rank", style="cyan", justify="right")
    table.add_column("Stop %", justify="right")
    table.add_column("Take %", justify="right")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Total Return", justify="right")
    table.add_column("Avg Win", justify="right")
    table.add_column("Avg Loss", justify="right")

    for i, r in enumerate(ranked):
        p = r["_params"]
        style = "bold green" if i < 3 else ""
        table.add_row(
            str(i + 1),
            f"{p['stop_loss_pct']*100:.1f}%",
            f"{p['take_profit_pct']*100:.1f}%",
            str(r["total_trades"]),
            f"{r['win_rate']:.1f}%",
            f"{r['profit_factor']:.2f}",
            f"${r['total_return']:+.2f}",
            f"${r['avg_win']:+.2f}",
            f"${r['avg_loss']:+.2f}",
            style=style,
        )

    console.print(table)

    # --- write top 3 to config/tuned_params.yaml ---
    top3 = ranked[:3]
    tuned = {}
    for rank_idx, r in enumerate(top3, start=1):
        p = r["_params"]
        tuned[f"bb_squeeze_rank_{rank_idx}"] = {
            "description": (
                f"Rank {rank_idx} — "
                f"Win Rate: {r['win_rate']:.1f}%, "
                f"Profit Factor: {r['profit_factor']:.2f}, "
                f"Return: ${r['total_return']:+.2f} on {r['total_trades']} trades"
            ),
            "bb_squeeze": {
                "squeeze_threshold": p["squeeze_threshold"],
                "min_signal_strength": p["min_signal_strength"],
            },
            "risk_manager": {
                "stop_loss_pct": p["stop_loss_pct"],
                "take_profit_pct": p["take_profit_pct"],
            },
        }

    out_path = Path("config/tuned_params.yaml")
    with out_path.open("w") as f:
        f.write("# Auto-generated by sweep_bb_squeeze.py\n")
        f.write(f"# Sweep date: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"# Pairs: {', '.join(PAIRS)} | Period: {DAYS_BACK} days | Balance: ${INITIAL_BALANCE}\n")
        f.write(f"# Fixed: squeeze_threshold={SQUEEZE_THRESHOLD}, "
                f"min_signal_strength={MIN_SIGNAL_STRENGTH}\n")
        f.write(f"# Sweep: stop_loss_pct × take_profit_pct\n")
        f.write(f"# Total combos tested: {total_combos} | Ranked by: win_rate → profit_factor → total_return\n\n")
        yaml.dump(tuned, f, default_flow_style=False, sort_keys=False)

    console.print(f"\n[bold green]✓ Top 3 param sets saved to {out_path}[/bold green]\n")


if __name__ == "__main__":
    main()
