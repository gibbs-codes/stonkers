"""Timeframe Comparison: 1-minute vs 15-minute candles.

This script runs backtests on the SAME strategies using both timeframes to answer:
- Which timeframe produces more actionable signals?
- Which timeframe has better win rates / profitability?
- Which timeframe is better for learning vs production?

Uses:
- 1-min: loose_params.yaml (designed for fast signal generation)
- 15-min: strategy_params.yaml (tighter, production-ready)

Output: analysis/timeframe_comparison.md
"""

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Tuple
import yaml

from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from rich.console import Console
from rich.table import Table

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy

console = Console()
load_dotenv()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
PAIRS = ["ETH/USD", "SOL/USD"]
DAYS_BACK = 30
INITIAL_BALANCE = Decimal("1000")

# Timeframe configurations
TIMEFRAME_CONFIGS = {
    "1-min": {
        "timeframe": TimeFrame(1, TimeFrameUnit.Minute),
        "params_file": "config/loose_params.yaml",
        "candle_limit": 30000,  # ~20 days of 1-min candles (limited by Alpaca)
        "description": "Fast signals, noise-heavy, good for scalping",
    },
    "15-min": {
        "timeframe": TimeFrame(15, TimeFrameUnit.Minute),
        "params_file": "config/strategy_params.yaml",
        "candle_limit": 3000,  # ~31 days of 15-min candles
        "description": "Slower signals, cleaner patterns, good for swing trading",
    },
}


@dataclass
class StrategyResult:
    """Results from a single strategy backtest."""
    strategy_name: str
    timeframe: str
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
    sharpe_ratio: float


def load_params(config_file: str) -> dict:
    """Load strategy parameters from YAML file."""
    path = Path(config_file)
    if not path.exists():
        console.print(f"[yellow]Warning: {config_file} not found, using defaults[/yellow]")
        return {}
    with path.open() as f:
        return yaml.safe_load(f) or {}


def create_strategies(params: dict) -> List:
    """Create strategy instances with given parameters."""
    # bb_squeeze may be None in YAML (comment-only section), so handle that
    bb_params = params.get("bb_squeeze") or {}
    return [
        EmaRsiStrategy(**params.get("ema_rsi", {})),
        EmaCrossoverStrategy(**params.get("ema_cross", {})),
        BollingerSqueezeStrategy(**bb_params),
        MomentumThrustStrategy(**params.get("momentum_thrust", {})),
        VwapMeanReversionStrategy(**params.get("vwap_mean_rev", {})),
        SupportResistanceBreakoutStrategy(**params.get("support_resistance_breakout", {})),
    ]


def calculate_sharpe_ratio(trades: List[Dict], risk_free_rate: float = 0.0) -> float:
    """Calculate Sharpe ratio from trade P&L list.

    Simplified: uses trade-level returns, assumes daily granularity.
    """
    if not trades or len(trades) < 2:
        return 0.0

    pnls = [t.get('pnl', 0) for t in trades if 'pnl' in t]
    if len(pnls) < 2:
        return 0.0

    import statistics
    mean_return = statistics.mean(pnls)
    std_dev = statistics.stdev(pnls)

    if std_dev == 0:
        return 0.0

    # Annualize (rough approximation for trading)
    sharpe = (mean_return - risk_free_rate) / std_dev
    return sharpe


def run_backtest_for_timeframe(
    timeframe_name: str,
    config: dict,
    alpaca: AlpacaConnector,
    start_date: datetime,
    end_date: datetime,
) -> Tuple[Dict[str, StrategyResult], Dict]:
    """Run backtests for all strategies at a given timeframe.

    Returns:
        Tuple of (strategy_results dict, combined_metrics dict)
    """
    console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"[bold cyan]  TIMEFRAME: {timeframe_name.upper()}[/bold cyan]")
    console.print(f"[bold cyan]{'='*60}[/bold cyan]")
    console.print(f"  Params: {config['params_file']}")
    console.print(f"  {config['description']}\n")

    # Fetch candles
    console.print("[dim]Fetching candle data...[/dim]")
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=PAIRS,
        timeframe=config["timeframe"],
        limit=config["candle_limit"],
    )

    for pair, candles in candles_by_pair.items():
        console.print(f"  {pair}: {len(candles)} candles")

    # Calculate actual date range from candles (may be less than requested)
    all_timestamps = sorted(set(
        c.timestamp for candles in candles_by_pair.values() for c in candles
    ))
    if not all_timestamps:
        console.print("[red]No candle data available![/red]")
        return {}, {}

    actual_start = all_timestamps[0]
    actual_end = all_timestamps[-1]
    actual_days = (actual_end - actual_start).days + 1
    console.print(f"  Date range: {actual_start.date()} to {actual_end.date()} ({actual_days} days)\n")

    # Load parameters
    params = load_params(config["params_file"])

    # Risk manager (same for both timeframes)
    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=Decimal("0.02"),
        take_profit_pct=Decimal("0.05"),
    )

    strategy_results: Dict[str, StrategyResult] = {}

    # Run each strategy individually
    strategies = create_strategies(params)
    for strategy in strategies:
        console.print(f"  Running: {strategy.name}...", end=" ")

        engine = BacktestEngine([strategy], risk_manager, INITIAL_BALANCE)
        metrics = engine.run(candles_by_pair, actual_start, actual_end)

        # Access trades from engine for Sharpe calculation
        sharpe = calculate_sharpe_ratio(engine.trades)

        # Calculate trades per day
        trades_per_day = metrics['total_trades'] / actual_days if actual_days > 0 else 0

        result = StrategyResult(
            strategy_name=strategy.name,
            timeframe=timeframe_name,
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
            sharpe_ratio=sharpe,
        )
        strategy_results[strategy.name] = result

        status = "[green]+" if result.total_pnl >= 0 else "[red]-"
        console.print(f"{result.total_trades} trades, {result.win_rate:.0f}% WR, "
                      f"{status}${abs(result.total_pnl):.2f}[/]")

    # Run all strategies combined
    console.print(f"\n  Running: ALL COMBINED...", end=" ")
    all_strategies = create_strategies(params)
    combined_engine = BacktestEngine(all_strategies, risk_manager, INITIAL_BALANCE)
    combined_metrics = combined_engine.run(candles_by_pair, actual_start, actual_end)
    combined_sharpe = calculate_sharpe_ratio(combined_engine.trades)
    combined_metrics['sharpe_ratio'] = combined_sharpe
    combined_metrics['trades_per_day'] = combined_metrics['total_trades'] / actual_days if actual_days > 0 else 0
    combined_metrics['actual_days'] = actual_days

    status = "[green]+" if float(combined_metrics['total_return']) >= 0 else "[red]-"
    console.print(f"{combined_metrics['total_trades']} trades, {combined_metrics['win_rate']:.0f}% WR, "
                  f"{status}${abs(float(combined_metrics['total_return'])):.2f}[/]")

    return strategy_results, combined_metrics


def generate_comparison_table(
    results_1min: Dict[str, StrategyResult],
    results_15min: Dict[str, StrategyResult],
) -> Table:
    """Generate a Rich comparison table."""
    table = Table(title="Strategy Comparison: 1-min vs 15-min", show_header=True)
    table.add_column("Strategy", style="cyan")
    table.add_column("TF", style="dim")
    table.add_column("Trades", justify="right")
    table.add_column("Trades/Day", justify="right")
    table.add_column("Win Rate", justify="right")
    table.add_column("Total P&L", justify="right")
    table.add_column("Max DD", justify="right")
    table.add_column("Sharpe", justify="right")
    table.add_column("Winner?", justify="center")

    all_strategies = set(results_1min.keys()) | set(results_15min.keys())

    for strategy in sorted(all_strategies):
        r1 = results_1min.get(strategy)
        r15 = results_15min.get(strategy)

        # Determine winner based on total P&L
        if r1 and r15:
            winner_1m = r1.total_pnl > r15.total_pnl
            winner_15m = r15.total_pnl > r1.total_pnl
        else:
            winner_1m = winner_15m = False

        # Add 1-min row
        if r1:
            pnl_style = "green" if r1.total_pnl >= 0 else "red"
            winner_mark = "[bold green]<<<[/bold green]" if winner_1m else ""
            table.add_row(
                strategy,
                "1m",
                str(r1.total_trades),
                f"{r1.trades_per_day:.1f}",
                f"{r1.win_rate:.0f}%",
                f"[{pnl_style}]${r1.total_pnl:+.2f}[/{pnl_style}]",
                f"{r1.max_drawdown:.1f}%",
                f"{r1.sharpe_ratio:.2f}",
                winner_mark,
            )

        # Add 15-min row
        if r15:
            pnl_style = "green" if r15.total_pnl >= 0 else "red"
            winner_mark = "[bold green]<<<[/bold green]" if winner_15m else ""
            table.add_row(
                "",  # strategy name already shown
                "15m",
                str(r15.total_trades),
                f"{r15.trades_per_day:.1f}",
                f"{r15.win_rate:.0f}%",
                f"[{pnl_style}]${r15.total_pnl:+.2f}[/{pnl_style}]",
                f"{r15.max_drawdown:.1f}%",
                f"{r15.sharpe_ratio:.2f}",
                winner_mark,
            )

        # Separator between strategies
        table.add_row("", "", "", "", "", "", "", "", "")

    return table


def generate_markdown_report(
    results_1min: Dict[str, StrategyResult],
    results_15min: Dict[str, StrategyResult],
    combined_1min: Dict,
    combined_15min: Dict,
) -> str:
    """Generate the full markdown comparison report."""

    lines = [
        "# Timeframe Comparison: 1-Minute vs 15-Minute Candles",
        "",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Pairs:** {', '.join(PAIRS)}",
        f"**Initial Balance:** ${INITIAL_BALANCE}",
        "",
        "---",
        "",
        "## Executive Summary",
        "",
    ]

    # Determine overall winner
    total_pnl_1m = float(combined_1min.get('total_return', 0))
    total_pnl_15m = float(combined_15min.get('total_return', 0))

    if total_pnl_15m > total_pnl_1m:
        winner = "15-minute"
        loser = "1-minute"
        margin = total_pnl_15m - total_pnl_1m
    else:
        winner = "1-minute"
        loser = "15-minute"
        margin = total_pnl_1m - total_pnl_15m

    lines.extend([
        f"**Winner: {winner.upper()} candles** outperformed by ${margin:.2f}",
        "",
        "| Metric | 1-Minute | 15-Minute |",
        "|--------|----------|-----------|",
        f"| Total Trades | {combined_1min.get('total_trades', 0)} | {combined_15min.get('total_trades', 0)} |",
        f"| Trades/Day | {combined_1min.get('trades_per_day', 0):.1f} | {combined_15min.get('trades_per_day', 0):.1f} |",
        f"| Win Rate | {combined_1min.get('win_rate', 0):.1f}% | {combined_15min.get('win_rate', 0):.1f}% |",
        f"| Total P&L | ${total_pnl_1m:+.2f} | ${total_pnl_15m:+.2f} |",
        f"| Max Drawdown | {combined_1min.get('max_drawdown', 0):.1f}% | {combined_15min.get('max_drawdown', 0):.1f}% |",
        f"| Sharpe Ratio | {combined_1min.get('sharpe_ratio', 0):.2f} | {combined_15min.get('sharpe_ratio', 0):.2f} |",
        f"| Final Equity | ${float(combined_1min.get('final_equity', INITIAL_BALANCE)):.2f} | ${float(combined_15min.get('final_equity', INITIAL_BALANCE)):.2f} |",
        "",
        "---",
        "",
        "## Per-Strategy Breakdown",
        "",
    ])

    # Strategy comparison table
    all_strategies = sorted(set(results_1min.keys()) | set(results_15min.keys()))

    lines.extend([
        "| Strategy | Timeframe | Trades | Trades/Day | Win Rate | P&L | Max DD | Sharpe |",
        "|----------|-----------|--------|------------|----------|-----|--------|--------|",
    ])

    for strategy in all_strategies:
        r1 = results_1min.get(strategy)
        r15 = results_15min.get(strategy)

        # Determine winner for this strategy
        if r1 and r15:
            winner_1m = r1.total_pnl > r15.total_pnl
        else:
            winner_1m = False

        if r1:
            mark = " **<<<**" if winner_1m else ""
            lines.append(
                f"| {strategy} | 1m | {r1.total_trades} | {r1.trades_per_day:.1f} | "
                f"{r1.win_rate:.0f}% | ${r1.total_pnl:+.2f}{mark} | {r1.max_drawdown:.1f}% | {r1.sharpe_ratio:.2f} |"
            )
        if r15:
            mark = " **<<<**" if r15 and not winner_1m and r1 else ""
            lines.append(
                f"| | 15m | {r15.total_trades} | {r15.trades_per_day:.1f} | "
                f"{r15.win_rate:.0f}% | ${r15.total_pnl:+.2f}{mark} | {r15.max_drawdown:.1f}% | {r15.sharpe_ratio:.2f} |"
            )

    lines.extend([
        "",
        "---",
        "",
        "## Signal Frequency Analysis",
        "",
        "### 1-Minute Candles",
        "",
    ])

    # Signal frequency for 1-min
    for name, r in sorted(results_1min.items(), key=lambda x: -x[1].trades_per_day):
        bar_len = int(r.trades_per_day * 5)  # Scale for visualization
        bar = "█" * min(bar_len, 50)
        lines.append(f"- **{name}**: {r.trades_per_day:.1f}/day {bar}")

    lines.extend([
        "",
        "### 15-Minute Candles",
        "",
    ])

    for name, r in sorted(results_15min.items(), key=lambda x: -x[1].trades_per_day):
        bar_len = int(r.trades_per_day * 5)
        bar = "█" * min(bar_len, 50)
        lines.append(f"- **{name}**: {r.trades_per_day:.1f}/day {bar}")

    lines.extend([
        "",
        "---",
        "",
        "## Profitability by Strategy",
        "",
        "### Winners (positive P&L in both timeframes)",
        "",
    ])

    winners_both = []
    winners_one = []
    losers_both = []

    for strategy in all_strategies:
        r1 = results_1min.get(strategy)
        r15 = results_15min.get(strategy)

        pnl_1m = r1.total_pnl if r1 else 0
        pnl_15m = r15.total_pnl if r15 else 0

        if pnl_1m > 0 and pnl_15m > 0:
            winners_both.append((strategy, pnl_1m, pnl_15m))
        elif pnl_1m > 0 or pnl_15m > 0:
            winners_one.append((strategy, pnl_1m, pnl_15m))
        else:
            losers_both.append((strategy, pnl_1m, pnl_15m))

    if winners_both:
        for s, p1, p15 in winners_both:
            lines.append(f"- **{s}**: 1m=${p1:+.2f}, 15m=${p15:+.2f}")
    else:
        lines.append("*None*")

    lines.extend([
        "",
        "### Winners (one timeframe only)",
        "",
    ])

    if winners_one:
        for s, p1, p15 in winners_one:
            better = "1m" if p1 > p15 else "15m"
            lines.append(f"- **{s}**: 1m=${p1:+.2f}, 15m=${p15:+.2f} (better at {better})")
    else:
        lines.append("*None*")

    lines.extend([
        "",
        "### Losers (negative P&L in both timeframes)",
        "",
    ])

    if losers_both:
        for s, p1, p15 in losers_both:
            lines.append(f"- **{s}**: 1m=${p1:+.2f}, 15m=${p15:+.2f}")
    else:
        lines.append("*None*")

    # Recommendations section
    lines.extend([
        "",
        "---",
        "",
        "## Recommendations",
        "",
        "### For Learning (clearer patterns)",
        "",
    ])

    # Analyze which timeframe has cleaner signals
    avg_wr_1m = sum(r.win_rate for r in results_1min.values()) / len(results_1min) if results_1min else 0
    avg_wr_15m = sum(r.win_rate for r in results_15min.values()) / len(results_15min) if results_15min else 0

    if avg_wr_15m > avg_wr_1m + 5:
        lines.extend([
            f"**Recommendation: 15-minute candles**",
            "",
            f"- Average win rate is {avg_wr_15m:.0f}% vs {avg_wr_1m:.0f}% on 1-minute",
            "- Patterns have more time to develop and confirm",
            "- Less noise from microstructure effects",
            "- Easier to identify and understand setups",
        ])
    elif avg_wr_1m > avg_wr_15m + 5:
        lines.extend([
            f"**Recommendation: 1-minute candles**",
            "",
            f"- Average win rate is {avg_wr_1m:.0f}% vs {avg_wr_15m:.0f}% on 15-minute",
            "- More frequent feedback loop for learning",
            "- But higher noise requires careful filtering",
        ])
    else:
        lines.extend([
            f"**Recommendation: Start with 15-minute candles**",
            "",
            f"- Win rates are similar ({avg_wr_1m:.0f}% vs {avg_wr_15m:.0f}%)",
            "- 15-min offers cleaner patterns with less noise",
            "- Easier to see cause-and-effect in strategies",
        ])

    lines.extend([
        "",
        "### For Profit Potential",
        "",
    ])

    if total_pnl_15m > total_pnl_1m:
        lines.extend([
            f"**Recommendation: 15-minute candles**",
            "",
            f"- Total P&L: ${total_pnl_15m:+.2f} vs ${total_pnl_1m:+.2f}",
            f"- Outperforms by ${margin:.2f}",
            "- Fewer trades means lower transaction cost impact",
            "- Better signal quality offsets lower frequency",
        ])
    else:
        lines.extend([
            f"**Recommendation: 1-minute candles**",
            "",
            f"- Total P&L: ${total_pnl_1m:+.2f} vs ${total_pnl_15m:+.2f}",
            f"- Outperforms by ${margin:.2f}",
            "- Higher frequency captures more opportunities",
            "- But requires tighter risk management",
        ])

    lines.extend([
        "",
        "### For Scalability (adding more strategies)",
        "",
    ])

    # Count how many strategies work at each timeframe
    working_1m = sum(1 for r in results_1min.values() if r.total_pnl > 0)
    working_15m = sum(1 for r in results_15min.values() if r.total_pnl > 0)

    if working_15m > working_1m:
        lines.extend([
            f"**Recommendation: 15-minute candles**",
            "",
            f"- {working_15m}/{len(results_15min)} strategies profitable vs {working_1m}/{len(results_1min)} on 1-min",
            "- More strategies work out-of-the-box",
            "- Pattern-based strategies need time to develop signals",
            "- Easier to add new strategies without retuning",
        ])
    elif working_1m > working_15m:
        lines.extend([
            f"**Recommendation: 1-minute candles**",
            "",
            f"- {working_1m}/{len(results_1min)} strategies profitable vs {working_15m}/{len(results_15min)} on 15-min",
            "- More strategies work at this timeframe",
            "- Higher frequency suits momentum/scalping strategies",
        ])
    else:
        lines.extend([
            f"**Recommendation: 15-minute candles**",
            "",
            f"- Equal number of profitable strategies ({working_15m})",
            "- 15-min is more robust for diverse strategy types",
            "- Easier to maintain and scale",
        ])

    lines.extend([
        "",
        "---",
        "",
        "## Final Verdict",
        "",
    ])

    # Score each timeframe
    score_1m = 0
    score_15m = 0

    if total_pnl_1m > total_pnl_15m:
        score_1m += 2
    else:
        score_15m += 2

    if avg_wr_1m > avg_wr_15m:
        score_1m += 1
    else:
        score_15m += 1

    if working_1m > working_15m:
        score_1m += 1
    else:
        score_15m += 1

    if combined_1min.get('sharpe_ratio', 0) > combined_15min.get('sharpe_ratio', 0):
        score_1m += 1
    else:
        score_15m += 1

    if combined_1min.get('max_drawdown', 100) < combined_15min.get('max_drawdown', 100):
        score_1m += 1
    else:
        score_15m += 1

    if score_15m > score_1m:
        verdict = "15-MINUTE CANDLES"
        verdict_reason = "Better overall metrics across profitability, win rate, and risk-adjusted returns."
    else:
        verdict = "1-MINUTE CANDLES"
        verdict_reason = "Higher frequency trading produces better results with these strategies."

    lines.extend([
        f"### **USE {verdict}**",
        "",
        f"Score: 1-min={score_1m}, 15-min={score_15m}",
        "",
        verdict_reason,
        "",
        "---",
        "",
        "*Report generated by compare_timeframes.py*",
    ])

    return "\n".join(lines)


def main():
    """Main entry point."""
    console.print("\n[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   TIMEFRAME COMPARISON: 1-MINUTE vs 15-MINUTE[/bold cyan]")
    console.print("[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]\n")

    # Initialize Alpaca connector
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    # Date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_BACK)

    console.print(f"[bold]Configuration:[/bold]")
    console.print(f"  Pairs: {', '.join(PAIRS)}")
    console.print(f"  Target Period: {start_date.date()} to {end_date.date()} ({DAYS_BACK} days)")
    console.print(f"  Starting Balance: ${INITIAL_BALANCE:,}")

    # Run backtests for each timeframe
    results_1min, combined_1min = run_backtest_for_timeframe(
        "1-min",
        TIMEFRAME_CONFIGS["1-min"],
        alpaca,
        start_date,
        end_date,
    )

    results_15min, combined_15min = run_backtest_for_timeframe(
        "15-min",
        TIMEFRAME_CONFIGS["15-min"],
        alpaca,
        start_date,
        end_date,
    )

    # Display comparison table
    console.print("\n")
    table = generate_comparison_table(results_1min, results_15min)
    console.print(table)

    # Generate and save markdown report
    report = generate_markdown_report(results_1min, results_15min, combined_1min, combined_15min)

    output_path = Path("analysis/timeframe_comparison.md")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report)

    console.print(f"\n[bold green]✓ Report saved to: {output_path}[/bold green]")

    # Print quick summary
    console.print("\n[bold]Quick Summary:[/bold]")
    pnl_1m = float(combined_1min.get('total_return', 0))
    pnl_15m = float(combined_15min.get('total_return', 0))

    if pnl_15m > pnl_1m:
        console.print(f"  [green]>>> 15-MINUTE wins by ${pnl_15m - pnl_1m:.2f}[/green]")
    else:
        console.print(f"  [green]>>> 1-MINUTE wins by ${pnl_1m - pnl_15m:.2f}[/green]")

    console.print(f"  1-min:  {combined_1min.get('total_trades', 0)} trades, "
                  f"{combined_1min.get('win_rate', 0):.0f}% WR, ${pnl_1m:+.2f}")
    console.print(f"  15-min: {combined_15min.get('total_trades', 0)} trades, "
                  f"{combined_15min.get('win_rate', 0):.0f}% WR, ${pnl_15m:+.2f}")


if __name__ == "__main__":
    main()
