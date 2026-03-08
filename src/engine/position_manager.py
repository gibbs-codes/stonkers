"""Position manager - single source of truth for positions."""
import logging
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from src.data.database import Database
from src.models.position import Position, PositionStatus

logger = logging.getLogger(__name__)


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

        # Validate loaded positions
        if self._cache:
            stale, warnings = self.validate_positions()
            if stale:
                logger.warning(
                    f"Found {len(stale)} potentially stale positions on startup. "
                    f"Consider verifying with exchange API."
                )
            for warning in warnings:
                logger.warning(warning)

    def validate_positions(
        self,
        max_age_hours: int = 24,
    ) -> Tuple[List[Position], List[str]]:
        """Validate loaded positions for potential issues.

        Checks:
        - Position age (might be stale from previous crash)
        - Data integrity

        Args:
            max_age_hours: Positions older than this trigger a warning

        Returns:
            Tuple of (stale_positions, warning_messages)
        """
        stale_positions = []
        warnings = []
        now = datetime.now(timezone.utc)

        for pair, position in self._cache.items():
            # Check for stale positions
            position_age = now - position.entry_time
            if position_age > timedelta(hours=max_age_hours):
                stale_positions.append(position)
                warnings.append(
                    f"Position {pair} is {position_age.total_seconds() / 3600:.1f} hours old. "
                    f"Entry: {position.entry_time}, may need manual verification."
                )

            # Check for data integrity
            if position.entry_price <= 0:
                warnings.append(f"Position {pair} has invalid entry price: {position.entry_price}")

            if position.quantity <= 0:
                warnings.append(f"Position {pair} has invalid quantity: {position.quantity}")

        return stale_positions, warnings

    def get_stale_positions(self, max_age_hours: int = 24) -> List[Position]:
        """Get positions that may be stale (old entries from previous session).

        Args:
            max_age_hours: Consider positions older than this as stale

        Returns:
            List of potentially stale positions
        """
        stale, _ = self.validate_positions(max_age_hours)
        return stale

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
