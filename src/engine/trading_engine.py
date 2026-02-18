"""Main trading engine - orchestrates the trading loop."""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Union

from rich.console import Console
from rich.table import Table

from src.analysis.range_detector import RangeDetector
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
        trader: Union[PaperTrader, "LiveTrader"],
    ):
        """Initialize trading engine.

        Args:
            db: Database instance
            strategies: List of strategies to execute
            risk_manager: Risk manager instance
            trader: Paper or live trader instance
        """
        self.db = db
        self.strategies = strategies
        self.risk_manager = risk_manager
        self.trader = trader
        self.position_manager = PositionManager(db)
        self.range_detector = RangeDetector()
        self._regime_cache: Dict[str, object] = {}

        # Keep backwards compatibility
        self.paper_trader = trader

        console.print("\n[bold green]Trading Engine Initialized[/bold green]")
        console.print(f"Strategies: {', '.join(s.name for s in strategies)}")
        console.print(f"Starting Balance: ${trader.get_account_value()}")
        console.print()

    def process_candles(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Process new candles for all pairs.

        This is the main loop that:
        0. Updates market regime for each pair
        1. Checks if existing positions should close
        2. Runs strategies to find new entry signals
        3. Opens new positions if signals pass risk checks

        Args:
            candles_by_pair: Dict mapping pair -> list of recent candles
        """
        # Step 0: Update market regimes
        self._update_regimes(candles_by_pair)

        # Step 1: Check existing positions for exits
        self._check_position_exits(candles_by_pair)

        # Step 2: Look for new entry signals
        self._check_entry_signals(candles_by_pair)

        # Step 3: Update account equity with unrealized P&L
        self._update_equity(candles_by_pair)

        # Step 4: Display status
        self._display_status()

    def _update_regimes(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Compute market regime for each pair."""
        for pair, candles in candles_by_pair.items():
            if candles and len(candles) >= 20:
                regime = self.range_detector.detect(candles)
                self._regime_cache[pair] = regime
                console.print(
                    f"[dim]{pair} regime: {regime.status} "
                    f"(bandwidth: {regime.bandwidth_pct:.2%})[/dim]"
                )
                try:
                    self.db.insert_regime_log(
                        datetime.now(timezone.utc), pair, regime
                    )
                except Exception:
                    pass

    def _find_strategy(self, strategy_name: str) -> Optional[Strategy]:
        """Find a strategy by name."""
        for s in self.strategies:
            if s.name == strategy_name:
                return s
        return None

    def _check_position_exits(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Check if any open positions should be closed.

        Uses strategy-specific exits first, then risk manager rules.

        Args:
            candles_by_pair: Dict mapping pair -> candles
        """
        for pair, position in list(self.position_manager.get_all_open().items()):
            if pair not in candles_by_pair:
                continue

            candles = candles_by_pair[pair]
            if not candles:
                continue

            current_price = candles[-1].close

            # Update trailing stop high-water mark
            self.risk_manager.update_high_water_mark(position, current_price)

            should_close = False
            reason = ""

            # 1. Check strategy-specific exit
            strategy = self._find_strategy(position.strategy_name)
            if strategy:
                exit_signal = strategy.should_exit(position, candles, current_price)
                if exit_signal and exit_signal.should_exit:
                    should_close = True
                    reason = exit_signal.reason

            # 2. If no strategy exit, check risk manager (SL/TP/trailing)
            if not should_close:
                should_close, reason = self.risk_manager.should_close_position(
                    position, current_price
                )

            if should_close:
                self.paper_trader.execute_exit(position, current_price)

                closed = self.position_manager.close_position(
                    pair, current_price, reason
                )

                self.risk_manager.clear_position_state(position.id)

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
            if self.position_manager.has_position(pair):
                continue

            if not candles:
                console.print(f"[red]{pair}: No candles received[/red]")
                continue

            # Run all strategies on this pair
            signal_found = False
            for strategy in self.strategies:
                # Set current regime context on strategy
                strategy.regime = self._regime_cache.get(pair)

                signal = strategy.analyze(candles)

                if not signal:
                    continue

                signal_found = True

                # Check if signal passes risk rules
                can_open, reason = self.risk_manager.can_open_position(
                    signal=signal,
                    open_positions_count=len(self.position_manager.get_all_open()),
                    has_position_for_pair=self.position_manager.has_position(pair),
                )

                if not can_open:
                    console.print(f"[dim]Signal blocked: {reason}[/dim]")
                    continue

                account_value = self.paper_trader.get_account_value()
                entry_price = candles[-1].close
                quantity = self.risk_manager.calculate_position_size(
                    account_value, entry_price
                )

                position = self.paper_trader.execute_entry(
                    signal, entry_price, quantity
                )

                if position is None:
                    console.print(f"[red]Entry execution failed for {pair}[/red]")
                    continue

                self.position_manager.open_position(position)

                console.print(
                    f"[bold green]OPENED {pair} {position.direction.value}:[/bold green] "
                    f"Price ${entry_price}, Qty {quantity:.4f}, "
                    f"Strategy: {strategy.name}"
                )
                console.print(f"  Reasoning: {signal.reasoning}")

                break

            # If no strategy generated a signal, print diagnostics
            if not signal_found:
                console.print(f"\n[dim][{pair}] No signals — {len(candles)} candles available[/dim]")
                for strategy in self.strategies:
                    try:
                        diag = strategy.diagnostics(candles)
                        parts = [f"{k}={v}" for k, v in diag.items()]
                        console.print(f"[dim]  {strategy.name}: {', '.join(parts)}[/dim]")
                    except Exception as e:
                        console.print(f"[dim]  {strategy.name}: diagnostics error: {e}[/dim]")

    def _update_equity(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Update account equity with unrealized P&L from open positions."""
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
        cash = self.paper_trader.get_cash_balance()
        equity = self.paper_trader.get_account_value()

        console.print(f"\n[bold]Account:[/bold] Cash ${cash:.2f} | Equity ${equity:.2f}")

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
