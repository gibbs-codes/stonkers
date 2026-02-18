"""Backtesting engine - test strategies on historical data."""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

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


class BacktestEngine:
    """Engine for backtesting strategies on historical data."""

    def __init__(
        self,
        strategies: List[Strategy],
        risk_manager: RiskManager,
        initial_balance: Decimal = Decimal("10000"),
        mtf_context=None,
        slippage_pct: float = 0.0,
        commission_pct: float = 0.0,
    ):
        """Initialize backtest engine.

        Args:
            strategies: List of strategies to test
            risk_manager: Risk manager instance
            initial_balance: Starting balance for backtest
            mtf_context: Optional multi-timeframe context
            slippage_pct: Simulated slippage as fraction (e.g. 0.0005 = 0.05%)
            commission_pct: Commission as fraction (e.g. 0.001 = 0.1%)
        """
        self.strategies = strategies
        self.risk_manager = risk_manager
        self.initial_balance = initial_balance
        self.mtf_context = mtf_context
        self.slippage_pct = Decimal(str(slippage_pct))
        self.commission_pct = Decimal(str(commission_pct))

        # Create temporary database for backtest
        self.db = Database(Path(":memory:"))  # In-memory SQLite
        self.paper_trader = PaperTrader(self.db, initial_balance)
        self.position_manager = PositionManager(self.db)
        self.range_detector = RangeDetector()

        # Track metrics
        self.trades: List[Dict] = []
        self.equity_curve: List[Dict] = []
        self._regime_cache: Dict[str, object] = {}

    def run(
        self,
        candles_by_pair: Dict[str, List[Candle]],
        start_date: datetime,
        end_date: datetime,
    ) -> Dict:
        """Run backtest on historical data.

        Args:
            candles_by_pair: Dict mapping pair -> list of historical candles
            start_date: Start date for backtest
            end_date: End date for backtest

        Returns:
            Dict of performance metrics
        """
        console.print(f"\n[bold cyan]Running Backtest[/bold cyan]")
        console.print(f"Period: {start_date.date()} to {end_date.date()}")
        console.print(f"Strategies: {', '.join(s.name for s in self.strategies)}")
        console.print(f"Starting Balance: ${self.initial_balance}")
        if self.slippage_pct > 0:
            console.print(f"Slippage: {float(self.slippage_pct)*100:.3f}%")
        if self.commission_pct > 0:
            console.print(f"Commission: {float(self.commission_pct)*100:.3f}%")
        console.print()

        # Filter candles to date range
        filtered_candles = self._filter_by_date(candles_by_pair, start_date, end_date)

        # Get all unique timestamps across all pairs
        all_timestamps = sorted(set(
            c.timestamp
            for candles in filtered_candles.values()
            for c in candles
        ))

        console.print(f"Processing {len(all_timestamps)} time periods...")

        # Replay history candle by candle
        for i, timestamp in enumerate(all_timestamps):
            # Get candles up to this timestamp for each pair
            current_candles = {}
            for pair, candles in filtered_candles.items():
                pair_candles = [c for c in candles if c.timestamp <= timestamp]
                if pair_candles:
                    current_candles[pair] = pair_candles

            # Process this timestamp (check exits, check entries)
            self._process_timestamp(current_candles, timestamp)

            # Record equity
            if i % 100 == 0:  # Sample every 100 candles
                self.equity_curve.append({
                    'timestamp': timestamp,
                    'equity': self.paper_trader.get_account_value(),
                })

        # Close any remaining positions at end
        self._close_all_positions(current_candles)

        # Calculate metrics
        metrics = self._calculate_metrics()

        # Display results
        self._display_results(metrics)

        return metrics

    def _filter_by_date(
        self,
        candles_by_pair: Dict[str, List[Candle]],
        start: datetime,
        end: datetime,
    ) -> Dict[str, List[Candle]]:
        """Filter candles to date range."""
        filtered = {}
        for pair, candles in candles_by_pair.items():
            filtered[pair] = [
                c for c in candles
                if start <= c.timestamp <= end
            ]
        return filtered

    def _apply_slippage(self, price: Decimal, is_buy: bool) -> Decimal:
        """Apply slippage to a fill price."""
        if self.slippage_pct == 0:
            return price
        if is_buy:
            return price * (Decimal("1") + self.slippage_pct)
        else:
            return price * (Decimal("1") - self.slippage_pct)

    def _apply_commission(self, value: Decimal) -> Decimal:
        """Calculate commission for a trade value."""
        return value * self.commission_pct

    def _process_timestamp(
        self,
        candles_by_pair: Dict[str, List[Candle]],
        timestamp: datetime,
    ) -> None:
        """Process a single timestamp (check exits and entries)."""
        # Step 0: Update market regimes
        for pair, candles in candles_by_pair.items():
            if candles and len(candles) >= 20:
                regime = self.range_detector.detect(candles)
                self._regime_cache[pair] = regime

        # Step 1: Check position exits
        for pair, position in list(self.position_manager.get_all_open().items()):
            if pair not in candles_by_pair or not candles_by_pair[pair]:
                continue

            current_price = candles_by_pair[pair][-1].close

            # Update trailing stop high-water mark
            self.risk_manager.update_high_water_mark(position, current_price)

            should_close = False
            reason = ""

            # 1. Check strategy-specific exit
            strategy = self._find_strategy(position.strategy_name)
            if strategy:
                exit_signal = strategy.should_exit(
                    position, candles_by_pair[pair], current_price
                )
                if exit_signal and exit_signal.should_exit:
                    should_close = True
                    reason = exit_signal.reason

            # 2. If no strategy exit, check risk manager (SL/TP/trailing)
            if not should_close:
                should_close, reason = self.risk_manager.should_close_position(
                    position, current_price
                )

            if should_close:
                # Apply slippage to exit
                is_buy = position.direction.value == "short"  # buy to close short
                exit_price = self._apply_slippage(current_price, is_buy)

                self.paper_trader.execute_exit(position, exit_price)
                closed = self.position_manager.close_position(
                    pair, exit_price, reason
                )

                self.risk_manager.clear_position_state(position.id)

                pnl = float(closed.realized_pnl())
                # Deduct commission from P&L
                if self.commission_pct > 0:
                    trade_value = float(position.entry_price * position.quantity)
                    pnl -= float(self._apply_commission(Decimal(str(trade_value)))) * 2  # entry + exit

                # Record trade
                self.trades.append({
                    'pair': pair,
                    'strategy': position.strategy_name,
                    'direction': position.direction.value,
                    'entry_time': position.entry_time,
                    'exit_time': closed.exit_time,
                    'entry_price': float(position.entry_price),
                    'exit_price': float(exit_price),
                    'quantity': float(position.quantity),
                    'pnl': pnl,
                    'reason': reason,
                })

        # Step 2: Check for new entry signals
        for pair, candles in candles_by_pair.items():
            if self.position_manager.has_position(pair):
                continue  # Already have position for this pair

            # Run all strategies
            for strategy in self.strategies:
                # Set current regime context on strategy
                strategy.regime = self._regime_cache.get(pair)

                signal = strategy.analyze(candles)

                if not signal:
                    continue

                # Higher timeframe alignment filter (single check, not duplicate)
                if not strategy.check_mtf_alignment(
                    signal, timestamp, self.mtf_context, getattr(strategy, "mtf_timeframe", "4h")
                ):
                    if hasattr(self.paper_trader, "log_signal"):
                        self.paper_trader.log_signal(
                            signal=signal,
                            status="rejected",
                            rejection_reason="mtf_mismatch",
                            expected_entry_price=candles[-1].close,
                        )
                    continue

                # Check risk rules
                can_open, reason = self.risk_manager.can_open_position(
                    signal=signal,
                    open_positions_count=len(self.position_manager.get_all_open()),
                    has_position_for_pair=False,
                )

                if not can_open:
                    if hasattr(self.paper_trader, "log_signal"):
                        self.paper_trader.log_signal(
                            signal=signal,
                            status="rejected",
                            rejection_reason=reason,
                            expected_entry_price=candles[-1].close,
                        )
                    continue

                # Open position with slippage
                account_value = self.paper_trader.get_account_value()
                raw_price = candles[-1].close
                is_buy = signal.signal_type.value in ("entry_long",)
                entry_price = self._apply_slippage(raw_price, is_buy)
                quantity = self.risk_manager.calculate_position_size(
                    account_value, entry_price
                )

                position = self.paper_trader.execute_entry(
                    signal, entry_price, quantity, expected_entry_price=raw_price
                )
                self.position_manager.open_position(position)

                # Only take first signal per pair
                break

    def _find_strategy(self, strategy_name: str) -> Optional[Strategy]:
        """Find a strategy by name."""
        for s in self.strategies:
            if s.name == strategy_name:
                return s
        return None

    def _close_all_positions(self, candles_by_pair: Dict[str, List[Candle]]) -> None:
        """Close all open positions at end of backtest."""
        for pair, position in list(self.position_manager.get_all_open().items()):
            if pair in candles_by_pair and candles_by_pair[pair]:
                current_price = candles_by_pair[pair][-1].close
                self.paper_trader.execute_exit(position, current_price)
                closed = self.position_manager.close_position(
                    pair, current_price, "End of backtest"
                )

                self.trades.append({
                    'pair': pair,
                    'strategy': position.strategy_name,
                    'direction': position.direction.value,
                    'entry_time': position.entry_time,
                    'exit_time': closed.exit_time,
                    'entry_price': float(position.entry_price),
                    'exit_price': float(current_price),
                    'quantity': float(position.quantity),
                    'pnl': float(closed.realized_pnl()),
                    'reason': "End of backtest",
                })

    def _calculate_metrics(self) -> Dict:
        """Calculate performance metrics."""
        if not self.trades:
            # Ensure downstream code always receives the full metrics shape even when
            # no trades were taken (prevents KeyError on display).
            final_equity = float(self.paper_trader.get_account_value())
            return {
                'total_return': 0.0,
                'total_return_pct': 0.0,
                'total_trades': 0,
                'winners': 0,
                'losers': 0,
                'win_rate': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'profit_factor': 0.0,
                'max_drawdown': 0.0,
                'final_equity': final_equity,
            }

        final_equity = self.paper_trader.get_account_value()
        total_return = final_equity - self.initial_balance
        total_return_pct = (total_return / self.initial_balance) * 100

        winners = [t for t in self.trades if t['pnl'] > 0]
        losers = [t for t in self.trades if t['pnl'] <= 0]

        win_rate = (len(winners) / len(self.trades)) * 100 if self.trades else 0

        avg_win = sum(t['pnl'] for t in winners) / len(winners) if winners else 0
        avg_loss = sum(t['pnl'] for t in losers) / len(losers) if losers else 0

        gross_profit = sum(t['pnl'] for t in winners)
        gross_loss = abs(sum(t['pnl'] for t in losers))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

        # Calculate max drawdown
        max_equity = float(self.initial_balance)
        max_drawdown = 0
        for point in self.equity_curve:
            equity = float(point['equity'])
            if equity > max_equity:
                max_equity = equity
            drawdown = ((max_equity - equity) / max_equity) * 100
            if drawdown > max_drawdown:
                max_drawdown = drawdown

        return {
            'total_return': float(total_return),
            'total_return_pct': float(total_return_pct),
            'total_trades': len(self.trades),
            'winners': len(winners),
            'losers': len(losers),
            'win_rate': float(win_rate),
            'avg_win': float(avg_win),
            'avg_loss': float(avg_loss),
            'profit_factor': float(profit_factor),
            'max_drawdown': float(max_drawdown),
            'final_equity': float(final_equity),
        }

    def _display_results(self, metrics: Dict) -> None:
        """Display backtest results."""
        console.print("\n[bold green]Backtest Results[/bold green]\n")

        # Summary table
        table = Table(title="Performance Summary")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", style="white")

        table.add_row("Total Return", f"${metrics['total_return']:+,.2f} ({metrics['total_return_pct']:+.2f}%)")
        table.add_row("Final Equity", f"${metrics['final_equity']:,.2f}")
        table.add_row("Total Trades", str(metrics['total_trades']))
        table.add_row("Win Rate", f"{metrics['win_rate']:.1f}%")
        table.add_row("Winners", str(metrics['winners']))
        table.add_row("Losers", str(metrics['losers']))
        table.add_row("Avg Win", f"${metrics['avg_win']:+.2f}")
        table.add_row("Avg Loss", f"${metrics['avg_loss']:+.2f}")
        table.add_row("Profit Factor", f"{metrics['profit_factor']:.2f}")
        table.add_row("Max Drawdown", f"{metrics['max_drawdown']:.2f}%")

        console.print(table)

        # Trade breakdown by strategy
        if self.trades:
            console.print("\n[bold]Performance by Strategy[/bold]\n")
            strategies_table = Table()
            strategies_table.add_column("Strategy")
            strategies_table.add_column("Trades")
            strategies_table.add_column("Win Rate")
            strategies_table.add_column("P&L")

            from collections import defaultdict
            strategy_stats = defaultdict(lambda: {'trades': 0, 'winners': 0, 'pnl': 0})

            for trade in self.trades:
                strat = trade['strategy']
                strategy_stats[strat]['trades'] += 1
                strategy_stats[strat]['pnl'] += trade['pnl']
                if trade['pnl'] > 0:
                    strategy_stats[strat]['winners'] += 1

            for strat, stats in strategy_stats.items():
                win_rate = (stats['winners'] / stats['trades']) * 100 if stats['trades'] > 0 else 0
                strategies_table.add_row(
                    strat,
                    str(stats['trades']),
                    f"{win_rate:.1f}%",
                    f"${stats['pnl']:+,.2f}"
                )

            console.print(strategies_table)
