"""Live trader for executing real trades via Alpaca API."""
from decimal import Decimal
from typing import Optional

from rich.console import Console

from src.connectors.alpaca import AlpacaConnector
from src.models.position import Position

console = Console()


class LiveTrader:
    """Live trader that executes real orders via Alpaca."""

    def __init__(self, alpaca: AlpacaConnector):
        """Initialize live trader.

        Args:
            alpaca: Alpaca connector instance
        """
        self.alpaca = alpaca
        console.print("[bold yellow]⚠️  LIVE TRADING MODE ENABLED[/bold yellow]")
        console.print("[yellow]Real money will be used for trades![/yellow]\n")

    def get_account_value(self) -> Decimal:
        """Get total account value (cash + positions).

        Returns:
            Total account equity
        """
        try:
            account = self.alpaca.get_account()
            return Decimal(str(account.equity))
        except Exception as e:
            console.print(f"[red]Error getting account value: {e}[/red]")
            return Decimal("0")

    def get_cash_balance(self) -> Decimal:
        """Get available cash balance.

        Returns:
            Available cash
        """
        try:
            account = self.alpaca.get_account()
            return Decimal(str(account.cash))
        except Exception as e:
            console.print(f"[red]Error getting cash balance: {e}[/red]")
            return Decimal("0")

    def execute_entry(self, position: Position, price: Decimal) -> bool:
        """Execute entry order for a position.

        Args:
            position: Position to enter
            price: Current market price

        Returns:
            True if order executed successfully
        """
        try:
            # Determine side
            side = "buy" if position.direction.value == "long" else "sell"

            # Place market order
            console.print(
                f"[bold yellow]PLACING LIVE ORDER:[/bold yellow] "
                f"{side.upper()} {position.quantity} {position.pair} @ ${price}"
            )

            order = self.alpaca.place_market_order(
                symbol=position.pair,
                qty=position.quantity,
                side=side
            )

            if order:
                console.print(f"[bold green]✓ Order placed:[/bold green] {order.id}")
                return True
            else:
                console.print("[bold red]✗ Order failed[/bold red]")
                return False

        except Exception as e:
            console.print(f"[bold red]Error placing order: {e}[/bold red]")
            return False

    def execute_exit(self, position: Position, price: Decimal) -> bool:
        """Execute exit order for a position.

        Args:
            position: Position to exit
            price: Current market price

        Returns:
            True if order executed successfully
        """
        try:
            # Determine side (opposite of entry)
            side = "sell" if position.direction.value == "long" else "buy"

            # Place market order
            console.print(
                f"[bold yellow]CLOSING LIVE POSITION:[/bold yellow] "
                f"{side.upper()} {position.quantity} {position.pair} @ ${price}"
            )

            order = self.alpaca.place_market_order(
                symbol=position.pair,
                qty=position.quantity,
                side=side
            )

            if order:
                console.print(f"[bold green]✓ Position closed:[/bold green] {order.id}")
                return True
            else:
                console.print("[bold red]✗ Close failed[/bold red]")
                return False

        except Exception as e:
            console.print(f"[bold red]Error closing position: {e}[/bold red]")
            return False

    def update_equity(self, unrealized_pnl: Decimal) -> None:
        """Update account equity (no-op for live trading - Alpaca tracks this).

        Args:
            unrealized_pnl: Unrealized P&L from open positions
        """
        # No-op: Alpaca automatically tracks equity for live accounts
        pass
