"""Main entry point for the trading bot."""
import os
import time
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from src.config.settings import Config
from src.connectors.alpaca import AlpacaConnector
from src.dashboard import init_dashboard, start_dashboard
from src.data.database import Database
from src.engine.live_trader import LiveTrader
from src.engine.paper_trader import PaperTrader
from src.engine.risk_manager import RiskManager
from src.engine.trading_engine import TradingEngine
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.rsi_divergence import RsiDivergenceStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy

console = Console()

# Load environment variables
load_dotenv()


def main():
    """Run the trading bot."""
    console.print("[bold cyan]🤖 Stonkers Trading Bot v2.0[/bold cyan]\n")

    # Load configuration
    config = Config.from_yaml(Path("config.yaml"))

    # Configuration
    PAIRS = config.trading.pairs
    INITIAL_BALANCE = config.paper_trading.starting_balance
    LOOP_INTERVAL = 60  # seconds

    # Initialize components
    console.print("[bold]Initializing components...[/bold]")

    # Database
    db = Database(Path("data/stonkers.db"))

    # Alpaca connector
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=config.exchange.paper,
    )

    # Risk manager
    risk_manager = RiskManager(
        max_positions=config.risk.max_open_positions,
        max_position_size_pct=config.risk.max_position_pct,
        stop_loss_pct=config.risk.stop_loss_pct,
        take_profit_pct=config.risk.take_profit_pct,
    )

    # Initialize trader (paper or live)
    if config.paper_trading.enabled:
        console.print("[bold cyan]📝 Paper Trading Mode[/bold cyan]")
        trader = PaperTrader(db, initial_balance=INITIAL_BALANCE)
    else:
        console.print("[bold yellow]⚡ LIVE TRADING MODE - REAL MONEY![/bold yellow]")
        trader = LiveTrader(alpaca)

    # Load strategies from config
    strategies = []

    # Load config.yaml to read strategy settings
    import yaml
    with open("config.yaml") as f:
        strategy_config = yaml.safe_load(f).get("strategies", {})

    # Map strategy names to classes
    strategy_map = {
        "ema_rsi": (EmaRsiStrategy, ["ema_period", "rsi_period", "rsi_oversold", "rsi_overbought", "min_signal_strength", "proximity_pct", "max_distance_from_ema_pct", "min_distance_from_ema_pct"]),
        "ema_crossover": (EmaCrossoverStrategy, ["fast_period", "slow_period", "min_signal_strength", "trend_filter_period", "trend_filter_buffer"]),
        "bollinger_squeeze": (BollingerSqueezeStrategy, ["bb_period", "bb_std", "squeeze_threshold", "min_signal_strength"]),
        "rsi_divergence": (RsiDivergenceStrategy, ["rsi_period", "lookback", "min_signal_strength"]),
        "momentum_thrust": (MomentumThrustStrategy, ["roc_period", "entry_threshold", "exit_threshold", "volume_multiplier", "min_signal_strength"]),
        "vwap_mean_reversion": (VwapMeanReversionStrategy, ["vwap_period", "std_multiplier", "volume_threshold", "min_signal_strength", "stretch_factor"]),
        "support_resistance_breakout": (SupportResistanceBreakoutStrategy, ["lookback_period", "level_tolerance", "min_touches", "volume_multiplier", "retest_candles", "retest_tolerance", "min_signal_strength"]),
    }

    # Load only enabled strategies
    for strategy_name, strategy_data in strategy_config.items():
        if strategy_data.get("enabled", False):
            if strategy_name in strategy_map:
                strategy_class, param_names = strategy_map[strategy_name]
                params = strategy_data.get("params", {})

                # Filter params to only include those the strategy accepts
                filtered_params = {k: v for k, v in params.items() if k in param_names}

                console.print(f"  ✓ Loading strategy: {strategy_name}")
                strategies.append(strategy_class(**filtered_params))

    if not strategies:
        console.print("[bold red]ERROR: No strategies enabled in config.yaml![/bold red]")
        console.print("Please enable at least one strategy before running.")
        return

    # Trading engine
    engine = TradingEngine(
        db=db,
        strategies=strategies,
        risk_manager=risk_manager,
        trader=trader,
    )

    # Start web dashboard
    DASHBOARD_PORT = 3004
    init_dashboard(db, trader, strategies, config, alpaca=alpaca)
    start_dashboard(port=DASHBOARD_PORT)
    console.print(f"[bold green]✓ Dashboard started on port {DASHBOARD_PORT}[/bold green]")

    console.print("[bold green]✓ All components initialized[/bold green]\n")
    console.print(f"Trading pairs: {', '.join(PAIRS)}")
    console.print(f"Loop interval: {LOOP_INTERVAL}s")
    console.print(f"Dashboard: http://localhost:{DASHBOARD_PORT}\n")
    console.print("[dim]Press Ctrl+C to stop[/dim]\n")

    # Main loop
    last_candles = {}  # Cache last successful candles
    try:
        while True:
            console.print(f"[bold blue]━━━ {time.strftime('%Y-%m-%d %H:%M:%S')} ━━━[/bold blue]")

            # Fetch latest candles
            try:
                candles_by_pair = alpaca.fetch_recent_candles(
                    pairs=PAIRS,
                    limit=200,  # Fetch enough for EMA100 + buffer
                )
                last_candles = candles_by_pair  # Cache successful fetch

                # Process candles through engine
                engine.process_candles(candles_by_pair)

            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {e}")

                # CRITICAL: Even if we can't fetch new candles, check exit conditions
                # using last known prices to protect against losses
                if last_candles:
                    console.print("[yellow]Using last known prices to check exit conditions...[/yellow]")
                    # Only check exits, don't look for new entries
                    for pair, candles in last_candles.items():
                        if engine.position_manager.has_position(pair) and candles:
                            position = engine.position_manager.get_position(pair)
                            current_price = candles[-1].close

                            should_close, reason = risk_manager.should_close_position(
                                position, current_price
                            )

                            if should_close:
                                trader.execute_exit(position, current_price)
                                closed = engine.position_manager.close_position(
                                    pair, current_price, reason
                                )
                                pnl = closed.realized_pnl()
                                console.print(
                                    f"[yellow]EMERGENCY CLOSE {pair} {position.direction.value}:[/yellow] "
                                    f"P&L: ${pnl:+.2f} ({reason})"
                                )

                    # Update equity with last known prices
                    total_unrealized = Decimal("0")
                    for pair, position in engine.position_manager.get_all_open().items():
                        if pair in last_candles and last_candles[pair]:
                            current_price = last_candles[pair][-1].close
                            unrealized = position.unrealized_pnl(current_price)
                            total_unrealized += unrealized
                    trader.update_equity(total_unrealized)

                    engine._display_status()
                else:
                    console.print("[red]No cached prices available - cannot check exit conditions[/red]")

                console.print("[yellow]Continuing to next iteration...[/yellow]\n")

            # Wait before next iteration
            time.sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Shutting down...[/bold yellow]")
        console.print(f"Final balance: ${trader.get_account_value():.2f}")
        console.print("[bold green]Goodbye![/bold green]")


if __name__ == "__main__":
    main()
