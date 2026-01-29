"""Main entry point for the trading bot."""
import os
import time
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

from src.config.settings import Config
from src.connectors.alpaca import AlpacaConnector
from src.data.database import Database
from src.engine.paper_trader import PaperTrader
from src.engine.risk_manager import RiskManager
from src.engine.trading_engine import TradingEngine
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.momentum_thrust import MomentumThrustStrategy
from src.strategies.vwap_mean_reversion import VwapMeanReversionStrategy
from src.strategies.support_resistance_breakout import SupportResistanceBreakoutStrategy

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
        paper=True,
    )

    # Risk manager
    risk_manager = RiskManager(
        max_positions=config.risk.max_open_positions,
        max_position_size_pct=config.risk.max_position_pct,
        stop_loss_pct=config.risk.stop_loss_pct,
        take_profit_pct=config.risk.take_profit_pct,
    )

    # Paper trader
    paper_trader = PaperTrader(db, initial_balance=INITIAL_BALANCE)

    # Strategies
    strategies = [
        EmaRsiStrategy(
            ema_period=100,
            rsi_period=14,
            rsi_oversold=30,
            rsi_overbought=70,
        ),
        EmaCrossoverStrategy(
            fast_period=9,
            slow_period=21,
        ),
        MomentumThrustStrategy(
            roc_period=14,
            entry_threshold=5.0,
            exit_threshold=2.0,
            volume_multiplier=1.5,
            min_signal_strength=0.6,
        ),
        VwapMeanReversionStrategy(
            vwap_period=50,
            std_multiplier=2.0,
            volume_threshold=1.5,
            min_signal_strength=0.6,
        ),
        SupportResistanceBreakoutStrategy(
            lookback_period=100,
            level_tolerance=0.01,
            min_touches=2,
            volume_multiplier=1.3,
            retest_candles=8,
            retest_tolerance=0.005,
            min_signal_strength=0.7,
        ),
    ]

    # Trading engine
    engine = TradingEngine(
        db=db,
        strategies=strategies,
        risk_manager=risk_manager,
        paper_trader=paper_trader,
    )

    console.print("[bold green]✓ All components initialized[/bold green]\n")
    console.print(f"Trading pairs: {', '.join(PAIRS)}")
    console.print(f"Loop interval: {LOOP_INTERVAL}s\n")
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
                                paper_trader.execute_exit(position, current_price)
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
                    paper_trader.update_equity(total_unrealized)

                    engine._display_status()
                else:
                    console.print("[red]No cached prices available - cannot check exit conditions[/red]")

                console.print("[yellow]Continuing to next iteration...[/yellow]\n")

            # Wait before next iteration
            time.sleep(LOOP_INTERVAL)

    except KeyboardInterrupt:
        console.print("\n[bold yellow]Shutting down...[/bold yellow]")
        console.print(f"Final balance: ${paper_trader.get_account_value():.2f}")
        console.print("[bold green]Goodbye![/bold green]")


if __name__ == "__main__":
    main()
