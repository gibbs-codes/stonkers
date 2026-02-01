"""Run backtest on historical data."""
import argparse
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import yaml

from dotenv import load_dotenv
from rich.console import Console

from src.connectors.alpaca import AlpacaConnector
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


def main():
    """Run backtests on all strategies."""
    parser = argparse.ArgumentParser(description="Run strategy backtests.")
    parser.add_argument(
        "-c",
        "--config",
        default="config/loose_params.yaml",
        help="YAML file with strategy parameters (default: config/loose_params.yaml)",
    )
    args = parser.parse_args()

    console.print("[bold cyan]═══════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   STONKERS BACKTEST RUNNER[/bold cyan]")
    console.print("[bold cyan]═══════════════════════════════════════[/bold cyan]\n")

    # Configuration
    PAIRS = ["ETH/USD", "SOL/USD"]
    DAYS_BACK = 30  # Test last 30 days
    INITIAL_BALANCE = Decimal("1000")  # Updated for real funding amount

    # Date range
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_BACK)

    console.print(f"[bold]Configuration:[/bold]")
    console.print(f"  Pairs: {', '.join(PAIRS)}")
    console.print(f"  Period: {start_date.date()} to {end_date.date()} ({DAYS_BACK} days)")
    console.print(f"  Starting Balance: ${INITIAL_BALANCE:,}")
    console.print()

    # Download historical data
    console.print("[bold]Downloading historical data...[/bold]")
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )

    # Fetch enough candles for the date range
    # 15 minute candles for 30 days = 30 * 24 * 4 = 2,880 candles
    # Alpaca limits to 10,000, so we have plenty of room
    from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=PAIRS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=3000,  # ~31 days of 15-min candles
    )

    for pair, candles in candles_by_pair.items():
        if candles:
            console.print(f"  ✓ {pair}: {len(candles)} candles")
        else:
            console.print(f"  ✗ {pair}: No data")

    if not any(candles_by_pair.values()):
        console.print("[red]No data available. Exiting.[/red]")
        return

    params = load_strategy_params(args.config)
    console.print(f"[dim]Params loaded from: {args.config}[/dim]\n")

    # Collect timeframes needed for MTF filter
    mtf_timeframes = set()

    # Initialize strategies (prefer YAML params when provided)
    strategies = [
        EmaCrossoverStrategy(**params.get("ema_cross", {})),
        BollingerSqueezeStrategy(**(params.get("bb_squeeze") or {})),
        MomentumThrustStrategy(**params.get("momentum_thrust", {})),
        VwapMeanReversionStrategy(**params.get("vwap_mean_rev", {})),
        SupportResistanceBreakoutStrategy(**params.get("support_resistance_breakout", {})),
        RangeTraderStrategy(**params.get("range_trader", {})),
    ]

    # Apply mtf config to strategies
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

    # Run backtest for ALL strategies together
    console.print("\n" + "="*60)
    console.print("[bold]TEST 1: All Strategies Combined[/bold]")
    console.print("="*60)

    engine = BacktestEngine(strategies, risk_manager, INITIAL_BALANCE)
    metrics = engine.run(candles_by_pair, start_date, end_date)

    # Run individual backtests for each strategy
    for strategy in strategies:
        console.print("\n" + "="*60)
        console.print(f"[bold]TEST: {strategy.name} Only[/bold]")
        console.print("="*60)

        single_engine = BacktestEngine([strategy], risk_manager, INITIAL_BALANCE)
        single_metrics = single_engine.run(candles_by_pair, start_date, end_date)

    console.print("\n[bold green]✓ Backtesting Complete![/bold green]\n")


if __name__ == "__main__":
    main()
