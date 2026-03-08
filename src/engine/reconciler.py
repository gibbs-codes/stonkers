"""Position reconciliation between bot's DB and Alpaca exchange."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List

from rich.console import Console

from src.connectors.alpaca import AlpacaConnector
from src.data.database import Database
from src.engine.position_manager import PositionManager
from src.models.position import Direction, Position, PositionStatus

console = Console()


class PositionReconciler:
    """Reconciles bot positions with exchange positions."""

    def __init__(
        self,
        alpaca: AlpacaConnector,
        position_manager: PositionManager,
        db: Database,
    ):
        self.alpaca = alpaca
        self.position_manager = position_manager
        self.db = db

    def reconcile(self) -> Dict[str, List]:
        """Run full reconciliation.

        Returns:
            Dict with keys 'adopted', 'stale_closed', 'matched'
        """
        results: Dict[str, List] = {"adopted": [], "stale_closed": [], "matched": []}

        exchange_positions = self._get_exchange_positions()
        db_positions = self.position_manager.get_all_open()

        exchange_pairs = set(exchange_positions.keys())
        db_pairs = set(db_positions.keys())

        # Positions on exchange but NOT in DB -> adopt as EXTERNAL
        for pair in exchange_pairs - db_pairs:
            try:
                adopted = self._adopt_position(exchange_positions[pair])
                results["adopted"].append(pair)
                self.db.insert_reconciliation_log(
                    "adopted", pair,
                    f"Adopted external {exchange_positions[pair]['side']} position "
                    f"qty={exchange_positions[pair]['quantity']}"
                )
                console.print(f"[yellow]RECONCILE: Adopted external position {pair}[/yellow]")
            except Exception as e:
                console.print(f"[red]RECONCILE: Failed to adopt {pair}: {e}[/red]")

        # Positions in DB but NOT on exchange -> close as stale
        for pair in db_pairs - exchange_pairs:
            try:
                self._close_stale_position(db_positions[pair])
                results["stale_closed"].append(pair)
                self.db.insert_reconciliation_log(
                    "stale_closed", pair,
                    "Position not found on exchange, closed in DB"
                )
                console.print(
                    f"[yellow]RECONCILE: Closed stale DB position {pair} "
                    f"(not on exchange)[/yellow]"
                )
            except Exception as e:
                console.print(f"[red]RECONCILE: Failed to close stale {pair}: {e}[/red]")

        # Matched positions
        for pair in exchange_pairs & db_pairs:
            results["matched"].append(pair)

        return results

    def _get_exchange_positions(self) -> Dict[str, dict]:
        """Get positions from Alpaca, normalized to pair format."""
        raw = self.alpaca.get_open_positions()
        positions: Dict[str, dict] = {}
        for pos in raw:
            symbol = pos.symbol
            pair = self._symbol_to_pair(symbol)
            qty = abs(float(pos.qty))
            positions[pair] = {
                "pair": pair,
                "quantity": Decimal(str(qty)),
                "side": "long" if float(pos.qty) > 0 else "short",
                "entry_price": Decimal(str(pos.avg_entry_price)),
                "current_price": Decimal(str(pos.current_price)),
                "unrealized_pnl": Decimal(str(pos.unrealized_pl)),
            }
        return positions

    def _symbol_to_pair(self, symbol: str) -> str:
        """Convert 'ETHUSD' to 'ETH/USD'."""
        if symbol.endswith("USD"):
            base = symbol[:-3]
            return f"{base}/USD"
        return symbol

    def _adopt_position(self, exchange_pos: dict) -> Position:
        """Create a Position in the DB for an orphaned exchange position."""
        direction = Direction.LONG if exchange_pos["side"] == "long" else Direction.SHORT
        position = Position(
            id=f"ext_{uuid.uuid4().hex[:8]}",
            pair=exchange_pos["pair"],
            direction=direction,
            entry_price=exchange_pos["entry_price"],
            quantity=exchange_pos["quantity"],
            entry_time=datetime.now(timezone.utc),
            strategy_name="EXTERNAL",
            status=PositionStatus.OPEN,
        )
        self.position_manager.open_position(position)
        return position

    def _close_stale_position(self, position: Position) -> None:
        """Close a DB position that doesn't exist on exchange."""
        self.position_manager.close_position(
            position.pair,
            position.entry_price,
            "Reconciliation: position not found on exchange",
        )
