"""Position manager - single source of truth for positions."""
from decimal import Decimal
from typing import Dict, List, Optional

from src.data.database import Database
from src.models.position import Position, PositionStatus


class PositionManager:
    """Manages position lifecycle with database as source of truth.

    Enforces business rules:
    - Only one position per pair at a time
    - Positions must be opened before closing
    - Database and memory cache stay in sync
    """

    def __init__(self, db: Database):
        """Initialize position manager.

        Args:
            db: Database instance
        """
        self.db = db
        self._cache: Dict[str, Position] = {}
        self._load_open_positions()

    def _load_open_positions(self) -> None:
        """Load open positions from database into memory cache."""
        positions = self.db.get_open_positions()
        self._cache = {p.pair: p for p in positions}

    def has_position(self, pair: str) -> bool:
        """Check if pair has an open position.

        Args:
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            True if pair has open position
        """
        return pair in self._cache

    def get_position(self, pair: str) -> Optional[Position]:
        """Get open position for pair.

        Args:
            pair: Trading pair

        Returns:
            Position object or None
        """
        return self._cache.get(pair)

    def get_all_open(self) -> Dict[str, Position]:
        """Get all open positions.

        Returns:
            Dict mapping pair -> Position
        """
        return dict(self._cache)

    def count_open(self) -> int:
        """Get count of open positions.

        Returns:
            Number of open positions
        """
        return len(self._cache)

    def open_position(self, position: Position) -> None:
        """Open new position.

        Database first, then cache. If database fails, cache stays unchanged.

        Args:
            position: Position to open

        Raises:
            ValueError: If pair already has position or position isn't OPEN
        """
        if self.has_position(position.pair):
            raise ValueError(f"Already have open position for {position.pair}")

        if position.status != PositionStatus.OPEN:
            raise ValueError("Can only open positions with OPEN status")

        # Database first (source of truth)
        self.db.insert_position(position)

        # Then cache
        self._cache[position.pair] = position

    def close_position(self, pair: str, exit_price: Decimal, reason: str) -> Position:
        """Close position for pair.

        Args:
            pair: Trading pair
            exit_price: Price at which to close
            reason: Reason for closing

        Returns:
            Closed position

        Raises:
            ValueError: If no open position for pair
        """
        position = self.get_position(pair)
        if not position:
            raise ValueError(f"No open position for {pair}")

        # Create closed position
        closed = position.close(exit_price, reason)

        # Database first
        self.db.update_position(closed)
        self.db.insert_trade(closed)

        # Then cache (remove from open positions)
        del self._cache[pair]

        return closed

    def get_total_exposure(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """Calculate total exposure across all positions.

        Args:
            current_prices: Dict of pair -> current price

        Returns:
            Total exposure value
        """
        exposure = Decimal("0")

        for position in self._cache.values():
            if position.pair in current_prices:
                position_value = position.quantity * position.entry_price
                exposure += position_value

        return exposure

    def get_total_unrealized_pnl(self, current_prices: Dict[str, Decimal]) -> Decimal:
        """Calculate total unrealized P&L across all positions.

        Args:
            current_prices: Dict of pair -> current price

        Returns:
            Total unrealized P&L
        """
        total_pnl = Decimal("0")

        for position in self._cache.values():
            if position.pair in current_prices:
                pnl = position.unrealized_pnl(current_prices[position.pair])
                total_pnl += pnl

        return total_pnl
