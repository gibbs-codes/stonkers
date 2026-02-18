"""Run backtest on historical data."""
import argparse
import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import yaml

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from src.connectors.alpaca import AlpacaConnector
from src.data.database import Database
from src.data.historical_data_manager import HistoricalDataManager
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.rsi_divergence import RsiDivergenceStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy
from src.strategies.range_trader import RangeTraderStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy
from src.analysis.mtf_context import MtfContext

console = Console()
load_dotenv()


def load_strategy_params(config_file: str = "config/loose_params.yaml") -> dict:
    """Load strategy parameters from a config file.

    Args:
        config_file: Path to YAML params file. Defaults to loose_params.yaml
                     for signal-generation testing. Use strategy_params.yaml for production.
    """
    config_path = Path(config_file)
    if not config_path.exists():
        console.print(f"[yellow]Warning: {config_file} not found, using strategy defaults[/yellow]")
        return {}
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


# Map of strategy name (lowercase) -> (class, config key for params file)
STRATEGY_REGISTRY = {
    "ema_rsi": (EmaRsiStrategy, "ema_rsi"),
    "ema_cross": (EmaCrossoverStrategy, "ema_cross"),
    "ema_crossover": (EmaCrossoverStrategy, "ema_cross"),
    "bb_squeeze": (BollingerSqueezeStrategy, "bb_squeeze"),
    "bollinger_squeeze": (BollingerSqueezeStrategy, "bb_squeeze"),
    "momentum_thrust": (MomentumThrustStrategy, "momentum_thrust"),
    "vwap_mean_rev": (VwapMeanReversionStrategy, "vwap_mean_rev"),
    "vwap_mean_reversion": (VwapMeanReversionStrategy, "vwap_mean_rev"),
    "support_resistance_breakout": (SupportResistanceBreakoutStrategy, "support_resistance_breakout"),
    "range_trader": (RangeTraderStrategy, "range_trader"),
    "rsi_divergence": (RsiDivergenceStrategy, "rsi_divergence"),
}


def _strip_mtf(d: dict) -> dict:
    """Remove MTF keys from params dict."""
    out = d.copy()
    out.pop("use_mtf_filter", None)
    out.pop("mtf_timeframe", None)
    return out


def _build_strategy(name: str, params: dict):
    """Build a strategy instance by name with params."""
    key = name.lower()
    if key not in STRATEGY_REGISTRY:
        raise ValueError(
            f"Unknown strategy '{name}'. Available: {', '.join(sorted(set(v[1] for v in STRATEGY_REGISTRY.values())))}"
        )
    cls, param_key = STRATEGY_REGISTRY[key]
    return cls(**_strip_mtf(params.get(param_key, {})))


def _list_runs(db_path: Path) -> None:
    """Display saved backtest runs."""
    if not db_path.exists():
        console.print("[red]No database found. Run a backtest with --save first.[/red]")
        return

    db = Database(db_path)
    runs = db.get_backtest_runs()
    db.close()

    if not runs:
        console.print("[dim]No saved backtest runs.[/dim]")
        return

    table = Table(title="Saved Backtest Runs")
    table.add_column("ID", style="dim")
    table.add_column("Date")
    table.add_column("Strategies")
    table.add_column("Pairs")
    table.add_column("Period")
    table.add_column("Return")
    table.add_column("Win Rate")
    table.add_column("Trades")
    table.add_column("PF")

    for run in runs:
        metrics = run.get("metrics", {})
        if isinstance(metrics, str):
            metrics = json.loads(metrics)

        ret = metrics.get("total_return_pct", 0)
        ret_style = "green" if ret >= 0 else "red"
        run_date = run.get("timestamp", "")
        table.add_row(
            str(run["id"])[:8],
            run_date[:16] if run_date else "",
            run.get("strategies", ""),
            run.get("pairs", ""),
            f"{run.get('start_date', '')[:10]} to {run.get('end_date', '')[:10]}",
            f"[{ret_style}]{ret:+.2f}%[/{ret_style}]",
            f"{metrics.get('win_rate', 0):.1f}%",
            str(metrics.get("total_trades", 0)),
            f"{metrics.get('profit_factor', 0):.2f}",
        )

    console.print(table)


def _save_results(args, strategies, pairs, start_date, end_date, balance, metrics, engine):
    """Save backtest results to the persistent database."""
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)

    strategy_names = ", ".join(s.name for s in strategies)
    pair_str = ", ".join(pairs)
    run_id = uuid.uuid4().hex[:12]

    params_info = {
        "slippage_pct": args.slippage,
        "commission_pct": args.commission,
        "config_file": args.config,
    }

    db.insert_backtest_run(
        run_id=run_id,
        timestamp=datetime.now(timezone.utc),
        strategies=strategy_names,
        pairs=pair_str,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        initial_balance=str(balance),
        final_equity=str(metrics.get("final_equity", 0)),
        metrics_json=json.dumps(metrics),
        params_json=json.dumps(params_info),
    )

    if engine.trades:
        db.insert_backtest_trades(run_id, engine.trades)

    if engine.equity_curve:
        db.insert_backtest_equity_curve(run_id, engine.equity_curve)

    db.close()
    console.print(f"\n[bold green]Results saved to {args.db} (run {run_id})[/bold green]")


def main():
    """Run backtests on strategies."""
    parser = argparse.ArgumentParser(
        description="Stonkers Backtest Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_backtest.py --strategy EMA_RSI --days 7 --pair ETH/USD
  python run_backtest.py --strategy BB_SQUEEZE --days 30 --save
  python run_backtest.py --days 14 --slippage 0.0005 --commission 0.001
  python run_backtest.py --start 2025-01-01 --end 2025-01-31
  python run_backtest.py --list-runs
""",
    )
    parser.add_argument(
        "-c", "--config",
        default="config/loose_params.yaml",
        help="YAML file with strategy parameters (default: config/loose_params.yaml)",
    )
    parser.add_argument(
        "--strategy",
        type=str,
        default=None,
        help="Run only this strategy (case-insensitive, e.g. EMA_RSI, bb_squeeze)",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Lookback period in days (default: 30)",
    )
    parser.add_argument(
        "--pair",
        type=str,
        default=None,
        help="Trade only this pair (e.g. ETH/USD). Default: all configured pairs",
    )
    parser.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Overrides --days",
    )
    parser.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Default: now",
    )
    parser.add_argument(
        "--balance",
        type=float,
        default=1000,
        help="Starting balance in USD (default: 1000)",
    )
    parser.add_argument(
        "--slippage",
        type=float,
        default=0.0,
        help="Slippage as fraction (e.g. 0.0005 = 0.05%%)",
    )
    parser.add_argument(
        "--commission",
        type=float,
        default=0.0,
        help="Commission as fraction (e.g. 0.001 = 0.1%%)",
    )
    parser.add_argument(
        "--save",
        action="store_true",
        help="Save results to data/stonkers.db for later comparison",
    )
    parser.add_argument(
        "--list-runs",
        action="store_true",
        help="List saved backtest runs and exit",
    )
    parser.add_argument(
        "--db",
        default="data/stonkers.db",
        help="Database path for --save and --list-runs (default: data/stonkers.db)",
    )
    args = parser.parse_args()

    # Handle --list-runs
    if args.list_runs:
        _list_runs(Path(args.db))
        return

    console.print("[bold cyan]═══════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   STONKERS BACKTEST RUNNER[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════[/bold cyan]\n")

    # Configuration
    PAIRS = [args.pair] if args.pair else ["ETH/USD", "SOL/USD"]
    INITIAL_BALANCE = Decimal(str(args.balance))

    # Date range
    if args.start:
        start_date = datetime.strptime(args.start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        start_date = datetime.now(timezone.utc) - timedelta(days=args.days)

    if args.end:
        end_date = datetime.strptime(args.end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    else:
        end_date = datetime.now(timezone.utc)

    console.print(f"[bold]Configuration:[/bold]")
    console.print(f"  Pairs: {', '.join(PAIRS)}")
    console.print(f"  Period: {start_date.date()} to {end_date.date()}")
    console.print(f"  Starting Balance: ${INITIAL_BALANCE:,}")
    if args.slippage > 0:
        console.print(f"  Slippage: {args.slippage*100:.3f}%")
    if args.commission > 0:
        console.print(f"  Commission: {args.commission*100:.3f}%")
    console.print()

    # Download historical data with caching + retries
    console.print("[bold]Downloading historical data...[/bold]")
    data_manager = HistoricalDataManager(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
    )

    candles_by_pair = data_manager.fetch_candles(
        symbols=PAIRS,
        timeframe="15m",
        start=start_date,
        end=end_date,
        incremental=True,
    )

    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    for pair, candles in candles_by_pair.items():
        if candles:
            console.print(f"  {pair}: {len(candles)} candles")
        else:
            console.print(f"  {pair}: No data")

    if not any(candles_by_pair.values()):
        console.print("[red]No data available. Exiting.[/red]")
        return

    params = load_strategy_params(args.config)
    console.print(f"[dim]Params loaded from: {args.config}[/dim]\n")

    # Build strategies
    if args.strategy:
        # Single strategy mode
        strategies = [_build_strategy(args.strategy, params)]
    else:
        # All strategies
        strategies = [
            EmaRsiStrategy(**_strip_mtf(params.get("ema_rsi", {}))),
            EmaCrossoverStrategy(**_strip_mtf(params.get("ema_cross", {}))),
            BollingerSqueezeStrategy(**_strip_mtf(params.get("bb_squeeze", {}))),
            MomentumThrustStrategy(**_strip_mtf(params.get("momentum_thrust", {}))),
            VwapMeanReversionStrategy(**_strip_mtf(params.get("vwap_mean_rev", {}))),
            SupportResistanceBreakoutStrategy(**_strip_mtf(params.get("support_resistance_breakout", {}))),
            RangeTraderStrategy(**_strip_mtf(params.get("range_trader", {}))),
            RsiDivergenceStrategy(**_strip_mtf(params.get("rsi_divergence", {}))),
        ]

    # Collect timeframes needed for MTF filter
    mtf_timeframes = set()
    for strat in strategies:
        cfg = params.get(strat.name.lower(), {}) if strat.name else {}
        strat.use_mtf_filter = cfg.get("use_mtf_filter", False)
        strat.mtf_timeframe = cfg.get("mtf_timeframe", "4h")
        mtf_timeframes.add(strat.mtf_timeframe)

    mtf_context = None
    if any(getattr(s, "use_mtf_filter", False) for s in strategies):
        mtf_context = MtfContext(alpaca, PAIRS, list(mtf_timeframes))

    # Risk manager
    risk_manager = RiskManager(
        max_positions=5,
        max_position_size_pct=Decimal("0.2"),
        stop_loss_pct=Decimal("0.02"),
        take_profit_pct=Decimal("0.05"),
    )

    # Run backtest
    if not args.strategy:
        console.print("\n" + "=" * 60)
        console.print("[bold]TEST 1: All Strategies Combined[/bold]")
        console.print("=" * 60)

    engine = BacktestEngine(
        strategies,
        risk_manager,
        INITIAL_BALANCE,
        mtf_context=mtf_context,
        slippage_pct=args.slippage,
        commission_pct=args.commission,
    )
    metrics = engine.run(candles_by_pair, start_date, end_date)

    # Save results if requested
    if args.save:
        _save_results(
            args, strategies, PAIRS, start_date, end_date,
            INITIAL_BALANCE, metrics, engine,
        )

    # Run individual backtests for each strategy (only in all-strategies mode)
    if not args.strategy:
        for strategy in strategies:
            console.print("\n" + "=" * 60)
            console.print(f"[bold]TEST: {strategy.name} Only[/bold]")
            console.print("=" * 60)

            single_engine = BacktestEngine(
                [strategy], risk_manager, INITIAL_BALANCE,
                mtf_context=mtf_context,
                slippage_pct=args.slippage,
                commission_pct=args.commission,
            )
            single_engine.run(candles_by_pair, start_date, end_date)

    console.print("\n[bold green]Backtesting Complete![/bold green]\n")


if __name__ == "__main__":
    main()
