"""Comprehensive trade and decision logging."""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler
from src.data.models import Signal, Trade, Position
from src.config.settings import config


class TradeLogger:
    """Logger for trading decisions and events."""

    def __init__(self):
        """Initialize trade logger."""
        # Create logs directory
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        # Set up logging
        log_level = getattr(logging, config.get('logging.level', 'INFO'))
        log_to_file = config.get('logging.log_to_file', True)

        # Console handler with Rich
        self.console = Console()
        handlers = [RichHandler(console=self.console, rich_tracebacks=True)]

        # File handler
        if log_to_file:
            log_file = log_dir / f"trading_{datetime.now().strftime('%Y%m%d')}.log"
            file_handler = logging.FileHandler(log_file)
            file_handler.setFormatter(
                logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
            )
            handlers.append(file_handler)

        # Configure logger
        logging.basicConfig(
            level=log_level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=handlers
        )

        self.logger = logging.getLogger("stonkers")

        # Decision log (JSON format)
        if log_to_file:
            self.decision_log_file = log_dir / f"decisions_{datetime.now().strftime('%Y%m%d')}.jsonl"
        else:
            self.decision_log_file = None

    def _log_decision(self, event_type: str, data: dict):
        """
        Log decision to JSON file.

        Args:
            event_type: Type of event
            data: Event data
        """
        if not self.decision_log_file:
            return

        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event_type': event_type,
            **data
        }

        with open(self.decision_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')

    def log_signal(self, signal: Signal):
        """
        Log a generated signal.

        Args:
            signal: Trading signal
        """
        if config.get('logging.log_signals', True):
            self.logger.info(
                f"[bold cyan]SIGNAL[/bold cyan] {signal.direction.value} "
                f"{signal.pair} | Strength: {signal.strength:.2f} | "
                f"Strategy: {signal.strategy_name}",
                extra={"markup": True}
            )
            self.logger.info(f"  Reasoning: {signal.reasoning}")

            self._log_decision('SIGNAL_GENERATED', signal.to_dict())

    def log_trade_decision(
        self,
        signal: Signal,
        action: str,
        reason: str,
        quantity: Optional[float] = None
    ):
        """
        Log a trade decision (taken or rejected).

        Args:
            signal: Trading signal
            action: 'OPENED', 'REJECTED', 'CLOSED'
            reason: Reason for decision
            quantity: Position quantity if applicable
        """
        if config.get('logging.log_decisions', True):
            if action == 'OPENED':
                self.logger.info(
                    f"[bold green]TRADE OPENED[/bold green] {signal.direction.value} "
                    f"{signal.pair} | Qty: {quantity:.6f} | {reason}",
                    extra={"markup": True}
                )
            elif action == 'REJECTED':
                self.logger.warning(
                    f"[bold yellow]TRADE REJECTED[/bold yellow] {signal.direction.value} "
                    f"{signal.pair} | {reason}",
                    extra={"markup": True}
                )
            elif action == 'CLOSED':
                self.logger.info(
                    f"[bold red]TRADE CLOSED[/bold red] {signal.pair} | {reason}",
                    extra={"markup": True}
                )

            self._log_decision('TRADE_DECISION', {
                'action': action,
                'signal': signal.to_dict(),
                'reason': reason,
                'quantity': quantity
            })

    def log_trade_completed(self, trade: Trade):
        """
        Log a completed trade.

        Args:
            trade: Completed trade
        """
        color = "green" if trade.is_winner else "red"
        self.logger.info(
            f"[bold {color}]TRADE COMPLETE[/bold {color}] {trade.pair} | "
            f"P&L: ${trade.pnl:.2f} ({trade.pnl_pct:.2f}%) | "
            f"Duration: {trade.duration_minutes:.1f}min",
            extra={"markup": True}
        )

        self._log_decision('TRADE_COMPLETED', trade.to_dict())

    def log_position_update(self, position: Position, current_price: float):
        """
        Log position update.

        Args:
            position: Open position
            current_price: Current market price
        """
        pnl = position.unrealized_pnl(current_price)
        pnl_pct = position.unrealized_pnl_pct(current_price)
        color = "green" if pnl > 0 else "red"

        self.logger.debug(
            f"[{color}]POSITION[/{color}] {position.pair} | "
            f"Unrealized P&L: ${pnl:.2f} ({pnl_pct:.2f}%)",
            extra={"markup": True}
        )

    def log_risk_check(self, passed: bool, reason: str):
        """
        Log risk management decision.

        Args:
            passed: Whether risk check passed
            reason: Reason for decision
        """
        if passed:
            self.logger.debug(f"[green]RISK CHECK PASSED[/green]: {reason}", extra={"markup": True})
        else:
            self.logger.warning(f"[red]RISK CHECK FAILED[/red]: {reason}", extra={"markup": True})

        self._log_decision('RISK_CHECK', {
            'passed': passed,
            'reason': reason
        })

    def log_portfolio_status(
        self,
        balance: float,
        portfolio_value: float,
        open_positions: int,
        total_return_pct: float
    ):
        """
        Log portfolio status.

        Args:
            balance: Current cash balance
            portfolio_value: Total portfolio value
            open_positions: Number of open positions
            total_return_pct: Total return percentage
        """
        color = "green" if total_return_pct >= 0 else "red"
        self.logger.info(
            f"[bold]PORTFOLIO[/bold] Balance: ${balance:.2f} | "
            f"Total Value: ${portfolio_value:.2f} | "
            f"Open Positions: {open_positions} | "
            f"[{color}]Return: {total_return_pct:+.2f}%[/{color}]",
            extra={"markup": True}
        )

    def log_error(self, error: Exception, context: str = ""):
        """
        Log an error.

        Args:
            error: Exception
            context: Additional context
        """
        self.logger.error(f"[bold red]ERROR[/bold red] {context}: {error}", extra={"markup": True})
        self._log_decision('ERROR', {
            'error': str(error),
            'context': context,
            'type': type(error).__name__
        })

    def log_info(self, message: str):
        """Log info message."""
        self.logger.info(message)

    def log_warning(self, message: str):
        """Log warning message."""
        self.logger.warning(message)

    def log_debug(self, message: str):
        """Log debug message."""
        self.logger.debug(message)
