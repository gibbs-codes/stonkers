"""Compare EMA+RSI strategy fixes: Baseline vs Conservative vs Aggressive.

Based on Session 4 diagnostic findings:
- Trades at RSI 38-41 had 20% win rate (the "falling knives")
- Trades at RSI 50-52 had 100% win rate
- Entries at 0-0.2% distance from EMA had 25% win rate
- Entries at 0.6-0.8% distance from EMA had 75% win rate

This script tests 3 parameter configurations:
1. Baseline: Old params (RSI 38/62, no min distance)
2. Conservative: RSI 45/57, min_distance 0.6%
3. Aggressive: RSI 50/50, min_distance 0.6%

Output: analysis/ema_rsi_fix_results.md
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from rich.console import Console
from rich.table import Table

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.strategies.ema_rsi import EmaRsiStrategy

console = Console()
load_dotenv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PAIRS = ["ETH/USD", "SOL/USD"]
DAYS_BACK = 30
INITIAL_BALANCE = Decimal("1000")

# Three parameter configurations to test
PARAM_CONFIGS = {
    "Baseline": {
        "description": "Original params (RSI 38/62, no min distance)",
        "params": {
            "rsi_oversold": 38,
            "rsi_overbought": 62,
            "min_signal_strength": Decimal("0.6"),
            "max_distance_from_ema_pct": 0.06,
            "min_distance_from_ema_pct": 0.0,  # No minimum
            "atr_period": 14,
            "atr_multiplier_stop": 1.5,
            "proximity_pct": 0.01,
        },
    },
    "Conservative": {
        "description": "Tighter RSI (45/57), min distance 0.6%",
        "params": {
            "rsi_oversold": 45,
            "rsi_overbought": 57,
            "min_signal_strength": Decimal("0.6"),
            "max_distance_from_ema_pct": 0.06,
            "min_distance_from_ema_pct": 0.006,  # 0.6% minimum
            "atr_period": 14,
            "atr_multiplier_stop": 1.5,
            "proximity_pct": 0.01,
        },
    },
    "Aggressive": {
        "description": "Full fix (RSI 50/50, min distance 0.6%)",
        "params": {
            "rsi_oversold": 50,
            "rsi_overbought": 50,
            "min_signal_strength": Decimal("0.6"),
            "max_distance_from_ema_pct": 0.06,
            "min_distance_from_ema_pct": 0.006,  # 0.6% minimum
            "atr_period": 14,
            "atr_multiplier_stop": 1.5,
            "proximity_pct": 0.01,
        },
    },
}


@dataclass
class BacktestResult:
    """Results from a single backtest run."""
    config_name: str
    description: str
    total_trades: int
    winners: int
    losers: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    final_equity: float
    trades_per_day: float


def run_backtest(
    config_name: str,
    config: dict,
    candles_by_pair: Dict,
    start_date: datetime,
    end_date: datetime,
    actual_days: int,
) -> BacktestResult:
    """Run a single backtest with the given configuration."""
    console.print(f"\n  [bold]{config_name}[/bold]: {config['description']}")

    # Create strategy with specific params
    strategy = EmaRsiStrategy(**config["params"])

    # Risk manager (same for all tests)
    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=Decimal("0.02"),
        take_profit_pct=Decimal("0.05"),
    )

    # Run backtest
    engine = BacktestEngine([strategy], risk_manager, INITIAL_BALANCE)
    metrics = engine.run(candles_by_pair, start_date, end_date)

    # Calculate trades per day
    trades_per_day = metrics['total_trades'] / actual_days if actual_days > 0 else 0

    result = BacktestResult(
        config_name=config_name,
        description=config['description'],
        total_trades=metrics['total_trades'],
        winners=metrics['winners'],
        losers=metrics['losers'],
        win_rate=metrics['win_rate'],
        total_pnl=float(metrics['total_return']),
        avg_win=float(metrics['avg_win']),
        avg_loss=float(metrics['avg_loss']),
        profit_factor=metrics['profit_factor'],
        max_drawdown=metrics['max_drawdown'],
        final_equity=float(metrics['final_equity']),
        trades_per_day=trades_per_day,
    )

    # Print summary
    pnl_style = "green" if result.total_pnl >= 0 else "red"
    console.print(f"    Trades: {result.total_trades} | "
                  f"Win Rate: {result.win_rate:.1f}% | "
                  f"P&L: [{pnl_style}]${result.total_pnl:+.2f}[/{pnl_style}] | "
                  f"PF: {result.profit_factor:.2f}")

    return result


def generate_comparison_table(results: List[BacktestResult]) -> Table:
    """Generate a Rich comparison table."""
    table = Table(title="EMA+RSI Parameter Comparison", show_header=True)
    table.add_column("Config", style="cyan")
    table.add_column("Trades", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Total P&L", justify="right")
    table.add_column("Profit Factor", justify="right")
    table.add_column("Max DD", justify="right")
    table.add_column("Improvement", justify="right")

    baseline_pnl = results[0].total_pnl if results else 0

    for r in results:
        pnl_style = "green" if r.total_pnl >= 0 else "red"
        wr_style = "green" if r.win_rate >= 50 else "yellow" if r.win_rate >= 40 else "red"
        pf_style = "green" if r.profit_factor >= 1.0 else "red"

        # Calculate improvement vs baseline
        if r.config_name == "Baseline":
            improvement = "---"
        else:
            delta = r.total_pnl - baseline_pnl
            improvement = f"[green]+${delta:.2f}[/green]" if delta >= 0 else f"[red]${delta:.2f}[/red]"

        table.add_row(
            r.config_name,
            str(r.total_trades),
            f"[{wr_style}]{r.win_rate:.1f}%[/{wr_style}]",
            f"[{pnl_style}]${r.total_pnl:+.2f}[/{pnl_style}]",
            f"[{pf_style}]{r.profit_factor:.2f}[/{pf_style}]",
            f"{r.max_drawdown:.1f}%",
            improvement,
        )

    return table


def generate_markdown_report(results: List[BacktestResult]) -> str:
    """Generate the full markdown comparison report."""
    baseline = results[0]
    conservative = results[1] if len(results) > 1 else None
    aggressive = results[2] if len(results) > 2 else None

    lines = [
        "# EMA+RSI Strategy Fix Results",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Pairs:** {', '.join(PAIRS)}",
        f"**Timeframe:** 15-minute candles",
        f"**Initial Balance:** ${INITIAL_BALANCE}",
        "",
        "---",
        "",
        "## Problem Statement",
        "",
        "Session 4 diagnostic revealed the EMA+RSI strategy was **catching falling knives**:",
        "",
        "- Trades at RSI 38-41 (just above oversold) had **20% win rate**",
        "- Trades at RSI 50-52 (stronger recovery) had **100% win rate**",
        "- Entries at 0-0.2% distance from EMA had **25% win rate** (noise)",
        "- Entries at 0.6-0.8% distance from EMA had **75% win rate** (real dislocation)",
        "",
        "---",
        "",
        "## Parameter Configurations Tested",
        "",
        "| Config | RSI Oversold | RSI Overbought | Min Distance | Description |",
        "|--------|--------------|----------------|--------------|-------------|",
        f"| Baseline | 38 | 62 | 0% | Original params |",
        f"| Conservative | 45 | 57 | 0.6% | Tighter RSI thresholds |",
        f"| Aggressive | 50 | 50 | 0.6% | Full fix per diagnostic |",
        "",
        "---",
        "",
        "## Results Comparison",
        "",
        "| Config | Trades | Win Rate | Total P&L | Profit Factor | Max DD | vs Baseline |",
        "|--------|--------|----------|-----------|---------------|--------|-------------|",
    ]

    for r in results:
        delta = r.total_pnl - baseline.total_pnl if r.config_name != "Baseline" else 0
        delta_str = f"+${delta:.2f}" if delta >= 0 else f"${delta:.2f}"
        if r.config_name == "Baseline":
            delta_str = "---"

        lines.append(
            f"| {r.config_name} | {r.total_trades} | {r.win_rate:.1f}% | "
            f"${r.total_pnl:+.2f} | {r.profit_factor:.2f} | {r.max_drawdown:.1f}% | {delta_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## Analysis",
        "",
    ])

    # Determine winner
    best = max(results, key=lambda r: r.total_pnl)
    worst = min(results, key=lambda r: r.total_pnl)

    lines.extend([
        f"### Best Performer: **{best.config_name}**",
        "",
        f"- Total P&L: **${best.total_pnl:+.2f}**",
        f"- Win Rate: **{best.win_rate:.1f}%**",
        f"- Profit Factor: **{best.profit_factor:.2f}**",
        f"- Max Drawdown: **{best.max_drawdown:.1f}%**",
        "",
    ])

    # Trade count analysis
    lines.extend([
        "### Trade Frequency Impact",
        "",
    ])

    if baseline.total_trades > 0:
        for r in results:
            if r.config_name != "Baseline":
                reduction = (1 - r.total_trades / baseline.total_trades) * 100
                lines.append(f"- **{r.config_name}**: {r.total_trades} trades "
                             f"({reduction:.0f}% reduction from baseline)")
    else:
        lines.append("- Baseline had 0 trades (no comparison possible)")

    lines.extend([
        "",
        "### Win Rate Improvement",
        "",
    ])

    for r in results:
        if r.config_name != "Baseline" and baseline.win_rate > 0:
            wr_delta = r.win_rate - baseline.win_rate
            lines.append(f"- **{r.config_name}**: {r.win_rate:.1f}% "
                         f"({wr_delta:+.1f}pp vs baseline)")

    lines.extend([
        "",
        "---",
        "",
        "## Recommendation",
        "",
    ])

    # Make recommendation based on results
    if best.total_pnl > baseline.total_pnl and best.win_rate > baseline.win_rate:
        lines.extend([
            f"### Use **{best.config_name}** Configuration",
            "",
            "The diagnostic-driven fixes successfully addressed the falling knife problem:",
            "",
            f"1. **Higher RSI threshold** filters out weak bounces that fail",
            f"2. **Minimum distance filter** skips noise near EMA",
            f"3. **Win rate improved** from {baseline.win_rate:.1f}% to {best.win_rate:.1f}%",
            f"4. **P&L improved** by ${best.total_pnl - baseline.total_pnl:+.2f}",
            "",
        ])
    elif best.config_name == "Baseline":
        lines.extend([
            "### Keep Baseline Configuration",
            "",
            "The proposed fixes did not improve performance:",
            "",
            "- Baseline outperformed the modified configurations",
            "- Consider testing with more data or different parameter values",
            "",
        ])
    else:
        lines.extend([
            f"### Consider **{best.config_name}** Configuration",
            "",
            "Mixed results - review trade-offs:",
            "",
            f"- P&L: ${best.total_pnl:+.2f} vs baseline ${baseline.total_pnl:+.2f}",
            f"- Win Rate: {best.win_rate:.1f}% vs baseline {baseline.win_rate:.1f}%",
            "",
        ])

    # Add recommended config
    if best.config_name != "Baseline":
        best_params = PARAM_CONFIGS[best.config_name]["params"]
        lines.extend([
            "### Recommended `strategy_params.yaml` Settings",
            "",
            "```yaml",
            "ema_rsi:",
            f"  rsi_oversold: {best_params['rsi_oversold']}",
            f"  rsi_overbought: {best_params['rsi_overbought']}",
            f"  min_signal_strength: {best_params['min_signal_strength']}",
            f"  max_distance_from_ema_pct: {best_params['max_distance_from_ema_pct']}",
            f"  min_distance_from_ema_pct: {best_params['min_distance_from_ema_pct']}",
            f"  atr_period: {best_params['atr_period']}",
            f"  atr_multiplier_stop: {best_params['atr_multiplier_stop']}",
            f"  proximity_pct: {best_params['proximity_pct']}",
            "```",
            "",
        ])

    lines.extend([
        "---",
        "",
        "*Report generated by compare_ema_rsi_fixes.py*",
    ])

    return "\n".join(lines)


def main():
    """Main entry point."""
    console.print("\n[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   EMA+RSI STRATEGY FIX COMPARISON[/bold cyan]")
    console.print("[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]\n")

    # Initialize Alpaca connector
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    # Fetch 15-minute candles
    console.print("[bold]Fetching 15-minute candle data...[/bold]")
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=PAIRS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=3000,
    )

    for pair, candles in candles_by_pair.items():
        console.print(f"  {pair}: {len(candles)} candles")

    # Calculate actual date range
    all_timestamps = sorted(set(
        c.timestamp for candles in candles_by_pair.values() for c in candles
    ))
    if not all_timestamps:
        console.print("[red]No candle data available![/red]")
        return

    start_date = all_timestamps[0]
    end_date = all_timestamps[-1]
    actual_days = (end_date - start_date).days + 1

    console.print(f"  Date range: {start_date.date()} to {end_date.date()} ({actual_days} days)")

    # Run backtests for each configuration
    console.print("\n[bold]Running backtests...[/bold]")
    results: List[BacktestResult] = []

    for config_name, config in PARAM_CONFIGS.items():
        result = run_backtest(
            config_name,
            config,
            candles_by_pair,
            start_date,
            end_date,
            actual_days,
        )
        results.append(result)

    # Display comparison table
    console.print("\n")
    table = generate_comparison_table(results)
    console.print(table)

    # Generate and save markdown report
    report = generate_markdown_report(results)

    output_path = Path("analysis/ema_rsi_fix_results.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)

    console.print(f"\n[bold green]Report saved to: {output_path}[/bold green]")

    # Print quick summary
    baseline = results[0]
    best = max(results, key=lambda r: r.total_pnl)

    console.print("\n[bold]Quick Summary:[/bold]")
    if best.config_name != "Baseline":
        improvement = best.total_pnl - baseline.total_pnl
        console.print(f"  [green]>>> {best.config_name} wins![/green]")
        console.print(f"  Improvement: ${improvement:+.2f}")
        console.print(f"  Win rate: {baseline.win_rate:.1f}% -> {best.win_rate:.1f}%")
    else:
        console.print(f"  Baseline performed best (${baseline.total_pnl:+.2f})")
        console.print(f"  The proposed fixes did not improve performance.")


if __name__ == "__main__":
    main()
