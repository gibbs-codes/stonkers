"""Main trading engine - orchestrates the trading loop."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List

from rich.console import Console
from rich.table import Table

from src.data.database import Database
from src.engine.paper_trader import PaperTrader
from src.engine.position_manager import PositionManager
from src.engine.risk_manager import RiskManager
from src.models.candle import Candle
from src.strategies.base import Strategy

console = Console()


class TradingEngine:
    """Main trading engine orchestrating strategy execution and risk management."""

    def __init__(
        self,
        db: Database,
        strategies: List[Strategy],
        risk_manager: RiskManager,
        paper_trader: PaperTrader,
    ):
        """Initialize trading engine.

        Args:
            db: Database instance
            strategies: List of strategies to execute
            risk_manager: Risk manager instance
            paper_trader: Paper trader instance
        """
        self.db = db
        self.strategies = strategies
        self.risk_manager = risk_manager
        self.paper_trader = paper_trader
        self.position_manager = PositionManager(db)

        console.print("\n[bold green]Trading Engine Initialized[/bold green]")
        console.print(f"Strategies: {', '.join(s.name for s in strategies)}")
        console.print(f"Starting Balance: ${paper_trader.get_account_value()}")
        console.print()

    def process_candles(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Process new candles for all pairs.

        This is the main loop that:
        1. Checks if existing positions should close
        2. Runs strategies to find new entry signals
        3. Opens new positions if signals pass risk checks

        Args:
            candles_by_pair: Dict mapping pair -> list of recent candles
        """
        # Step 1: Check existing positions for exits
        self._check_position_exits(candles_by_pair)

        # Step 2: Look for new entry signals
        self._check_entry_signals(candles_by_pair)

        # Step 3: Update account equity with unrealized P&L
        self._update_equity(candles_by_pair)

        # Step 4: Display status
        self._display_status()

    def _check_position_exits(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Check if any open positions should be closed.

        Args:
            candles_by_pair: Dict mapping pair -> candles
        """
        for pair, position in list(self.position_manager.get_all_open().items()):
            if pair not in candles_by_pair:
                continue

            # Get current price from latest candle
            current_price = candles_by_pair[pair][-1].close

            # Check if risk rules say to close
            should_close, reason = self.risk_manager.should_close_position(
                position, current_price
            )

            if should_close:
                # Execute exit
                self.paper_trader.execute_exit(position, current_price)

                # Close position in manager
                closed = self.position_manager.close_position(
                    pair, current_price, reason
                )

                # Log the close
                pnl = closed.realized_pnl()
                console.print(
                    f"[yellow]CLOSED {pair} {position.direction.value}:[/yellow] "
                    f"Entry ${position.entry_price}, Exit ${current_price}, "
                    f"P&L: ${pnl:+.2f} ({reason})"
                )

    def _check_entry_signals(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Check strategies for new entry signals.

        Args:
            candles_by_pair: Dict mapping pair -> candles
        """
        for pair, candles in candles_by_pair.items():
            # Skip if we already have a position for this pair
            if self.position_manager.has_position(pair):
                continue

            # Run all strategies on this pair
            for strategy in self.strategies:
                signal = strategy.analyze(candles)

                if not signal:
                    continue

                # Check if signal passes risk rules
                can_open, reason = self.risk_manager.can_open_position(
                    signal=signal,
                    open_positions_count=len(self.position_manager.get_all_open()),
                    has_position_for_pair=self.position_manager.has_position(pair),
                )

                if not can_open:
                    console.print(f"[dim]Signal blocked: {reason}[/dim]")
                    continue

                # Calculate position size
                account_value = self.paper_trader.get_account_value()
                entry_price = candles[-1].close
                quantity = self.risk_manager.calculate_position_size(
                    account_value, entry_price
                )

                # Execute entry
                position = self.paper_trader.execute_entry(
                    signal, entry_price, quantity
                )

                # Open position in manager
                self.position_manager.open_position(position)

                # Log the entry
                console.print(
                    f"[bold green]OPENED {pair} {position.direction.value}:[/bold green] "
                    f"Price ${entry_price}, Qty {quantity:.4f}, "
                    f"Strategy: {strategy.name}"
                )
                console.print(f"  Reasoning: {signal.reasoning}")

                # Only take first signal per pair per iteration
                break

    def _update_equity(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Update account equity with unrealized P&L from open positions.

        Args:
            candles_by_pair: Dict mapping pair -> candles
        """
        total_unrealized = Decimal("0")

        for pair, position in self.position_manager.get_all_open().items():
            if pair not in candles_by_pair:
                continue

            current_price = candles_by_pair[pair][-1].close
            unrealized = position.unrealized_pnl(current_price)
            total_unrealized += unrealized

        self.paper_trader.update_equity(total_unrealized)

    def _display_status(self) -> None:
        """Display current trading status."""
        # Account summary
        cash = self.paper_trader.get_cash_balance()
        equity = self.paper_trader.get_account_value()

        console.print(f"\n[bold]Account:[/bold] Cash ${cash:.2f} | Equity ${equity:.2f}")

        # Open positions
        open_positions = self.position_manager.get_all_open()
        if open_positions:
            table = Table(title="Open Positions")
            table.add_column("Pair")
            table.add_column("Direction")
            table.add_column("Entry")
            table.add_column("Quantity")
            table.add_column("Strategy")

            for pair, pos in open_positions.items():
                table.add_row(
                    pair,
                    pos.direction.value,
                    f"${pos.entry_price:.2f}",
                    f"{pos.quantity:.4f}",
                    pos.strategy_name,
                )

            console.print(table)
        else:
            console.print("[dim]No open positions[/dim]")

        console.print()
