"""SQLite storage for candles, trades, and positions."""
import sqlite3
from pathlib import Path
from typing import List, Optional
from datetime import datetime
from src.data.models import Candle, Trade, Position, Direction


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str = "data/trading.db"):
        """
        Initialize database connection.

        Args:
            db_path: Path to SQLite database file
        """
        # Ensure data directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        """Create database tables if they don't exist."""
        cursor = self.conn.cursor()

        # Candles table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS candles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                pair TEXT NOT NULL,
                timeframe TEXT NOT NULL,
                open REAL NOT NULL,
                high REAL NOT NULL,
                low REAL NOT NULL,
                close REAL NOT NULL,
                volume REAL NOT NULL,
                UNIQUE(timestamp, pair, timeframe)
            )
        """)

        # Trades table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                exit_price REAL NOT NULL,
                quantity REAL NOT NULL,
                pnl REAL NOT NULL,
                pnl_pct REAL NOT NULL,
                strategy_name TEXT NOT NULL,
                entry_timestamp TEXT NOT NULL,
                exit_timestamp TEXT NOT NULL,
                exit_reason TEXT,
                commission REAL DEFAULT 0,
                duration_minutes REAL
            )
        """)

        # Positions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY,
                pair TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                entry_timestamp TEXT NOT NULL,
                strategy_name TEXT NOT NULL,
                stop_loss REAL,
                take_profit REAL,
                is_open INTEGER DEFAULT 1
            )
        """)

        # Paper trading state table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS paper_trading_state (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                balance REAL NOT NULL,
                starting_balance REAL NOT NULL,
                last_updated TEXT NOT NULL
            )
        """)

        self.conn.commit()

    def store_candles(self, candles: List[Candle]):
        """Store candles in database."""
        cursor = self.conn.cursor()

        for candle in candles:
            cursor.execute("""
                INSERT OR REPLACE INTO candles
                (timestamp, pair, timeframe, open, high, low, close, volume)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                candle.timestamp.isoformat(),
                candle.pair,
                candle.timeframe,
                candle.open,
                candle.high,
                candle.low,
                candle.close,
                candle.volume
            ))

        self.conn.commit()

    def get_candles(
        self,
        pair: str,
        timeframe: str,
        limit: int = 100,
        since: datetime = None
    ) -> List[Candle]:
        """Retrieve candles from database."""
        cursor = self.conn.cursor()

        if since:
            cursor.execute("""
                SELECT * FROM candles
                WHERE pair = ? AND timeframe = ? AND timestamp >= ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pair, timeframe, since.isoformat(), limit))
        else:
            cursor.execute("""
                SELECT * FROM candles
                WHERE pair = ? AND timeframe = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (pair, timeframe, limit))

        rows = cursor.fetchall()

        candles = []
        for row in rows:
            candles.append(Candle(
                timestamp=datetime.fromisoformat(row['timestamp']),
                pair=row['pair'],
                timeframe=row['timeframe'],
                open=row['open'],
                high=row['high'],
                low=row['low'],
                close=row['close'],
                volume=row['volume']
            ))

        # Return in chronological order
        return list(reversed(candles))

    def store_trade(self, trade: Trade):
        """Store completed trade in database."""
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT INTO trades
            (id, timestamp, pair, direction, entry_price, exit_price, quantity,
             pnl, pnl_pct, strategy_name, entry_timestamp, exit_timestamp,
             exit_reason, commission, duration_minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            trade.id,
            trade.timestamp.isoformat(),
            trade.pair,
            trade.direction.value,
            trade.entry_price,
            trade.exit_price,
            trade.quantity,
            trade.pnl,
            trade.pnl_pct,
            trade.strategy_name,
            trade.entry_timestamp.isoformat(),
            trade.exit_timestamp.isoformat(),
            trade.exit_reason,
            trade.commission,
            trade.duration_minutes
        ))

        self.conn.commit()

    def store_position(self, position: Position):
        """Store open position in database."""
        cursor = self.conn.cursor()

        cursor.execute("""
            INSERT OR REPLACE INTO positions
            (id, pair, direction, entry_price, quantity, entry_timestamp,
             strategy_name, stop_loss, take_profit, is_open)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (
            position.id,
            position.pair,
            position.direction.value,
            position.entry_price,
            position.quantity,
            position.entry_timestamp.isoformat(),
            position.strategy_name,
            position.stop_loss,
            position.take_profit
        ))

        self.conn.commit()

    def close_position(self, position_id: str):
        """Mark position as closed."""
        cursor = self.conn.cursor()
        cursor.execute("""
            UPDATE positions SET is_open = 0 WHERE id = ?
        """, (position_id,))
        self.conn.commit()

    def get_open_positions(self) -> List[Position]:
        """Get all open positions."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM positions WHERE is_open = 1
        """)

        rows = cursor.fetchall()
        positions = []

        for row in rows:
            positions.append(Position(
                id=row['id'],
                pair=row['pair'],
                direction=Direction(row['direction']),
                entry_price=row['entry_price'],
                quantity=row['quantity'],
                entry_timestamp=datetime.fromisoformat(row['entry_timestamp']),
                strategy_name=row['strategy_name'],
                stop_loss=row['stop_loss'],
                take_profit=row['take_profit']
            ))

        return positions

    def save_paper_trading_state(self, balance: float, starting_balance: float):
        """Save paper trading balance state."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO paper_trading_state
            (id, balance, starting_balance, last_updated)
            VALUES (1, ?, ?, ?)
        """, (balance, starting_balance, datetime.now().isoformat()))
        self.conn.commit()

    def load_paper_trading_state(self) -> tuple[float, float]:
        """
        Load paper trading balance state.

        Returns:
            Tuple of (current_balance, starting_balance)
        """
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT balance, starting_balance FROM paper_trading_state WHERE id = 1
        """)

        row = cursor.fetchone()
        if row:
            return row['balance'], row['starting_balance']
        return None, None

    def close(self):
        """Close database connection."""
        self.conn.close()
