"""Database layer for persistent storage."""
import json
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Dict, List, Optional

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
        # Enable WAL mode for better concurrent read/write (dashboard thread)
        self.conn.execute("PRAGMA journal_mode=WAL")
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

        # Equity snapshots (time-series for P&L tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS equity_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                cash TEXT NOT NULL,
                equity TEXT NOT NULL,
                unrealized_pnl TEXT NOT NULL,
                num_positions INTEGER NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_equity_snapshots_ts
            ON equity_snapshots(timestamp)
        """)

        # Backtest runs (persist backtest results for comparison)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_runs (
                id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                strategies TEXT NOT NULL,
                pairs TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                initial_balance TEXT NOT NULL,
                final_equity TEXT NOT NULL,
                metrics_json TEXT NOT NULL,
                params_json TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        # Backtest trades (per-run trade records)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES backtest_runs(id),
                pair TEXT NOT NULL,
                strategy TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_time TEXT NOT NULL,
                exit_time TEXT NOT NULL,
                entry_price TEXT NOT NULL,
                exit_price TEXT NOT NULL,
                quantity TEXT NOT NULL,
                pnl TEXT NOT NULL,
                fees TEXT,
                reason TEXT
            )
        """)

        # Backtest equity curve (per-run equity snapshots)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS backtest_equity_curve (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL REFERENCES backtest_runs(id),
                timestamp TEXT NOT NULL,
                equity TEXT NOT NULL
            )
        """)

        # Regime logs (market regime tracking)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS regime_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                pair TEXT NOT NULL,
                status TEXT NOT NULL,
                support TEXT,
                resistance TEXT,
                bandwidth_pct TEXT,
                touches INTEGER
            )
        """)

        # Reconciliation logs
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reconciliation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                action TEXT NOT NULL,
                pair TEXT NOT NULL,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
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

    # --- Equity snapshots ---
    def insert_equity_snapshot(
        self,
        timestamp: datetime,
        cash: Decimal,
        equity: Decimal,
        unrealized_pnl: Decimal,
        num_positions: int,
    ) -> None:
        """Record an equity snapshot for P&L tracking."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO equity_snapshots (timestamp, cash, equity, unrealized_pnl, num_positions)
            VALUES (?, ?, ?, ?, ?)
        """, (
            timestamp.isoformat(),
            str(cash),
            str(equity),
            str(unrealized_pnl),
            num_positions,
        ))
        self.conn.commit()

    def get_equity_snapshots(self, since: Optional[datetime] = None, limit: int = 1000) -> list:
        """Get equity snapshots for reporting."""
        cursor = self.conn.cursor()
        if since:
            cursor.execute("""
                SELECT timestamp, cash, equity, unrealized_pnl, num_positions
                FROM equity_snapshots
                WHERE timestamp >= ?
                ORDER BY timestamp ASC
                LIMIT ?
            """, (since.isoformat(), limit))
        else:
            cursor.execute("""
                SELECT timestamp, cash, equity, unrealized_pnl, num_positions
                FROM equity_snapshots
                ORDER BY timestamp ASC
                LIMIT ?
            """, (limit,))

        return [
            {
                'timestamp': row['timestamp'],
                'cash': Decimal(row['cash']),
                'equity': Decimal(row['equity']),
                'unrealized_pnl': Decimal(row['unrealized_pnl']),
                'num_positions': row['num_positions'],
            }
            for row in cursor.fetchall()
        ]

    def get_trades_by_strategy(
        self,
        strategy_name: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> list:
        """Get trades with full columns for per-strategy reporting."""
        cursor = self.conn.cursor()
        query = """
            SELECT id, pair, direction, entry_price, exit_price, quantity,
                   entry_time, exit_time, pnl, pnl_pct, strategy_name, exit_reason
            FROM trades
            WHERE 1=1
        """
        params: list = []
        if strategy_name:
            query += " AND strategy_name = ?"
            params.append(strategy_name)
        if since:
            query += " AND exit_time >= ?"
            params.append(since.isoformat())
        query += " ORDER BY exit_time DESC"

        cursor.execute(query, params)
        return [
            {
                'id': row['id'],
                'pair': row['pair'],
                'direction': row['direction'],
                'entry_price': Decimal(row['entry_price']),
                'exit_price': Decimal(row['exit_price']),
                'quantity': Decimal(row['quantity']),
                'entry_time': row['entry_time'],
                'exit_time': row['exit_time'],
                'pnl': Decimal(row['pnl']),
                'pnl_pct': Decimal(row['pnl_pct']),
                'strategy_name': row['strategy_name'],
                'exit_reason': row['exit_reason'],
            }
            for row in cursor.fetchall()
        ]

    # --- Backtest persistence ---
    def insert_backtest_run(
        self,
        run_id: str,
        timestamp: datetime,
        strategies: str,
        pairs: str,
        start_date: str,
        end_date: str,
        initial_balance: str,
        final_equity: str,
        metrics_json: str,
        params_json: str,
    ) -> None:
        """Persist a backtest run."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO backtest_runs (
                id, timestamp, strategies, pairs, start_date, end_date,
                initial_balance, final_equity, metrics_json, params_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, timestamp.isoformat(), strategies, pairs,
            start_date, end_date, initial_balance, final_equity,
            metrics_json, params_json,
        ))
        self.conn.commit()

    def insert_backtest_trades(self, run_id: str, trades: List[Dict]) -> None:
        """Bulk insert backtest trades."""
        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO backtest_trades (
                run_id, pair, strategy, direction, entry_time, exit_time,
                entry_price, exit_price, quantity, pnl, fees, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            (
                run_id, t['pair'], t['strategy'], t['direction'],
                str(t['entry_time']), str(t['exit_time']),
                str(t['entry_price']), str(t['exit_price']),
                str(t['quantity']), str(t['pnl']),
                str(t.get('fees', 0)), t.get('reason', ''),
            )
            for t in trades
        ])
        self.conn.commit()

    def insert_backtest_equity_curve(self, run_id: str, curve: List[Dict]) -> None:
        """Bulk insert backtest equity curve."""
        cursor = self.conn.cursor()
        cursor.executemany("""
            INSERT INTO backtest_equity_curve (run_id, timestamp, equity)
            VALUES (?, ?, ?)
        """, [(run_id, str(p['timestamp']), str(p['equity'])) for p in curve])
        self.conn.commit()

    def get_backtest_runs(self, limit: int = 20) -> list:
        """Get recent backtest runs."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT id, timestamp, strategies, pairs, start_date, end_date,
                   initial_balance, final_equity, metrics_json, params_json
            FROM backtest_runs
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,))
        return [
            {
                'id': row['id'],
                'timestamp': row['timestamp'],
                'strategies': row['strategies'],
                'pairs': row['pairs'],
                'start_date': row['start_date'],
                'end_date': row['end_date'],
                'initial_balance': row['initial_balance'],
                'final_equity': row['final_equity'],
                'metrics': json.loads(row['metrics_json']),
                'params': json.loads(row['params_json']),
            }
            for row in cursor.fetchall()
        ]

    # --- Regime logging ---
    def insert_regime_log(self, timestamp: datetime, pair: str, regime) -> None:
        """Log market regime detection."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO regime_logs (timestamp, pair, status, support, resistance, bandwidth_pct, touches)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            timestamp.isoformat(), pair, regime.status,
            str(regime.support), str(regime.resistance),
            str(regime.bandwidth_pct), regime.touches,
        ))
        self.conn.commit()

    # --- Reconciliation logging ---
    def insert_reconciliation_log(self, action: str, pair: str, details: str = "") -> None:
        """Log a reconciliation action."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO reconciliation_logs (timestamp, action, pair, details)
            VALUES (?, ?, ?, ?)
        """, (datetime.now(timezone.utc).isoformat(), action, pair, details))
        self.conn.commit()

    def close(self):
        """Close database connection."""
        self.conn.close()
