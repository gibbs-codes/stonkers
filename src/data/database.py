"""Database layer for persistent storage."""
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from src.models.position import Position, PositionStatus, Direction


class Database:
    """SQLite database for positions, trades, and candles.

    Database is the single source of truth for all state.
    """

    def __init__(self, db_path: Path = Path("data/stonkers.db")):
        """Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row  # Access columns by name
        self._create_tables()

    def _create_tables(self):
        """Create database schema if it doesn't exist."""
        cursor = self.conn.cursor()

        # Positions table (source of truth for open/closed positions)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                status TEXT NOT NULL,
                exit_price TEXT,
                exit_time TEXT,
                exit_reason TEXT,
                stop_loss_price TEXT,
                take_profit_price TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Backwards-compat: add columns if table already existed
        for column in ("stop_loss_price", "take_profit_price", "signal_id"):
            try:
                cursor.execute(f"ALTER TABLE positions ADD COLUMN {column} TEXT")
            except sqlite3.OperationalError:
                # Column likely exists already
                pass

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_status
            ON positions(status)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_positions_pair
            ON positions(pair)
        """)

        # Trades table (closed positions for analysis)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                exit_price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                pnl TEXT NOT NULL,
                pnl_pct TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                exit_reason TEXT,
                signal_id INTEGER,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Signal logs for paper/backtest comparison
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS signal_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                pair TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                signal_type TEXT NOT NULL,
                strength REAL,
                status TEXT NOT NULL, -- accepted / rejected
                rejection_reason TEXT,
                expected_entry_price REAL,
                actual_entry_price REAL,
                expected_exit_price REAL,
                actual_exit_price REAL,
                quantity REAL,
                pnl_expected REAL,
                pnl_actual REAL,
                slippage REAL,
                position_id TEXT,
                notes TEXT
            )
        """)

        # Account state (single row for cash/equity tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS account_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                cash TEXT NOT NULL,
                equity TEXT NOT NULL,
                last_updated TEXT NOT NULL
            )
        """)

        # Candles cache (for backtesting)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                pair TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                open TEXT NOT NULL,
                high TEXT NOT NULL,
                low TEXT NOT NULL,
                close TEXT NOT NULL,
                volume TEXT NOT NULL,
                PRIMARY KEY (pair, timestamp)
            )
        """)

        self.conn.commit()

    def insert_position(self, position: Position) -> None:
        """Insert new position into database.

        Args:
            position: Position to insert
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO positions (
                id, pair, direction, entry_price, quantity, entry_time,
                strategy_name, status, exit_price, exit_time, exit_reason,
                stop_loss_price, take_profit_price, signal_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id,
            position.pair,
            position.direction.value,
            str(position.entry_price),
            str(position.quantity),
            position.entry_time.isoformat(),
            position.strategy_name,
            position.status.value,
            str(position.exit_price) if position.exit_price else None,
            position.exit_time.isoformat() if position.exit_time else None,
            position.exit_reason,
            str(position.stop_loss_price) if position.stop_loss_price else None,
            str(position.take_profit_price) if position.take_profit_price else None,
            position.signal_id,
        ))
        self.conn.commit()

    def update_position(self, position: Position) -> None:
        """Update existing position in database.

        Args:
            position: Position to update
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE positions
            SET status = ?, exit_price = ?, exit_time = ?, exit_reason = ?
            WHERE id = ?
        """, (
            position.status.value,
            str(position.exit_price) if position.exit_price else None,
            position.exit_time.isoformat() if position.exit_time else None,
            position.exit_reason,
            position.id
        ))
        self.conn.commit()

    def get_open_positions(self) -> List[Position]:
        """Get all open positions from database.

        Returns:
            List of open Position objects
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM positions
            WHERE status = ?
            ORDER BY entry_time DESC
        """, (PositionStatus.OPEN.value,))

        positions = []
        for row in cursor.fetchall():
            positions.append(self._row_to_position(row))

        return positions

    def get_position(self, position_id: str) -> Optional[Position]:
        """Get position by ID.

        Args:
            position_id: Position ID

        Returns:
            Position object or None if not found
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM positions WHERE id = ?", (position_id,))
        row = cursor.fetchone()

        if row:
            return self._row_to_position(row)
        return None

    def insert_trade(self, position: Position) -> None:
        """Insert closed position as trade record.

        Args:
            position: Closed position to record as trade
        """
        if position.status != PositionStatus.CLOSED:
            raise ValueError("Can only insert closed positions as trades")

        pnl = position.realized_pnl()
        pnl_pct = position.realized_pnl_pct()

        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO trades (
                id, pair, direction, entry_price, exit_price, quantity,
                entry_time, exit_time, pnl, pnl_pct, strategy_name, exit_reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            position.id,
            position.pair,
            position.direction.value,
            str(position.entry_price),
            str(position.exit_price),
            str(position.quantity),
            position.entry_time.isoformat(),
            position.exit_time.isoformat(),
            str(pnl),
            str(pnl_pct),
            position.strategy_name,
            position.exit_reason
        ))
        self.conn.commit()

    def get_account_state(self) -> Optional[dict]:
        """Get current account state.

        Returns:
            Dict with cash, equity, last_updated or None
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM account_state WHERE id = 1")
        row = cursor.fetchone()

        if row:
            return {
                'cash': Decimal(row['cash']),
                'equity': Decimal(row['equity']),
                'last_updated': row['last_updated']
            }
        return None

    def save_account_state(self, cash: Decimal, equity: Decimal) -> None:
        """Save account state.

        Args:
            cash: Current cash balance
            equity: Current equity (cash + unrealized P&L)
        """
        cursor = self.conn.cursor()

        # Upsert (insert or replace)
        cursor.execute("""
            INSERT OR REPLACE INTO account_state (id, cash, equity, last_updated)
            VALUES (1, ?, ?, ?)
        """, (
            str(cash),
            str(equity),
            datetime.now(timezone.utc).isoformat()
        ))
        self.conn.commit()

    def _row_to_position(self, row: sqlite3.Row) -> Position:
        """Convert database row to Position object.

        Args:
            row: SQLite row

        Returns:
            Position object
        """
        return Position(
            id=row['id'],
            pair=row['pair'],
            direction=Direction(row['direction']),
            entry_price=Decimal(row['entry_price']),
            quantity=Decimal(row['quantity']),
            entry_time=datetime.fromisoformat(row['entry_time']),
            strategy_name=row['strategy_name'],
            status=PositionStatus(row['status']),
            exit_price=Decimal(row['exit_price']) if row['exit_price'] else None,
            exit_time=datetime.fromisoformat(row['exit_time']) if row['exit_time'] else None,
            exit_reason=row['exit_reason'] or "",
            stop_loss_price=Decimal(row['stop_loss_price']) if row['stop_loss_price'] else None,
            take_profit_price=Decimal(row['take_profit_price']) if row['take_profit_price'] else None,
            signal_id=row['signal_id'] if 'signal_id' in row.keys() else None,
        )

    # --- Signal logging helpers ---
    def insert_signal_log(
        self,
        *,
        timestamp: datetime,
        pair: str,
        strategy_name: str,
        signal_type: str,
        strength: float,
        status: str,
        rejection_reason: str | None = None,
        expected_entry_price: float | None = None,
        actual_entry_price: float | None = None,
        quantity: float | None = None,
        slippage: float | None = None,
        position_id: str | None = None,
    ) -> int:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            INSERT INTO signal_logs (
                timestamp, pair, strategy_name, signal_type, strength, status,
                rejection_reason, expected_entry_price, actual_entry_price,
                quantity, slippage, position_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp.isoformat(),
                pair,
                strategy_name,
                signal_type,
                strength,
                status,
                rejection_reason,
                expected_entry_price,
                actual_entry_price,
                quantity,
                slippage,
                position_id,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_signal_log_exit(
        self,
        position_id: str,
        actual_exit_price: float,
        pnl_actual: float,
        pnl_expected: float | None = None,
        expected_exit_price: float | None = None,
    ) -> None:
        cursor = self.conn.cursor()
        cursor.execute(
            """
            UPDATE signal_logs
            SET actual_exit_price = ?, pnl_actual = ?, pnl_expected = COALESCE(pnl_expected, ?),
                expected_exit_price = COALESCE(expected_exit_price, ?)
            WHERE position_id = ?
            """,
            (actual_exit_price, pnl_actual, pnl_expected, expected_exit_price, position_id),
        )
        self.conn.commit()

    def get_recent_trades(self, limit: int = 10) -> list:
        """Get recent closed trades.

        Args:
            limit: Maximum number of trades to return

        Returns:
            List of trade dicts with pair, direction, pnl, pnl_pct
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT pair, direction, pnl, pnl_pct, exit_time
            FROM trades
            ORDER BY exit_time DESC
            LIMIT ?
        """, (limit,))

        trades = []
        for row in cursor.fetchall():
            trades.append({
                'pair': row['pair'],
                'direction': row['direction'],
                'pnl': Decimal(row['pnl']),
                'pnl_pct': Decimal(row['pnl_pct']),
                'exit_time': row['exit_time'],
            })
        return trades

    def close(self):
        """Close database connection."""
        self.conn.close()
