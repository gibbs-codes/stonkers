"""Emergency stop module to halt trading under adverse conditions."""
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Dict, List

from src.data.database import Database
from src.engine.position_manager import PositionManager


class EmergencyStop:
    """Monitors risk triggers and halts trading if tripped."""

    def __init__(
        self,
        db: Database,
        position_manager: PositionManager,
        max_consecutive_losses: int = 5,
        max_daily_loss_pct: Decimal = Decimal("0.03"),
    ):
        self.db = db
        self.position_manager = position_manager
        self.max_consecutive_losses = max_consecutive_losses
        self.max_daily_loss_pct = max_daily_loss_pct
        self.tripped = False
        self.last_check_day = None

    def _daily_pnl_pct(self) -> Decimal:
        """Compute today's realized P&L % from trades table."""
        conn = self.db.conn
        today = date.today().isoformat()
        rows = conn.execute(
            "SELECT pnl FROM trades WHERE date(exit_time)=?", (today,)
        ).fetchall()
        if not rows:
            return Decimal("0")
        pnl_sum = sum(Decimal(r["pnl"]) for r in rows)
        # assume account state equity as denominator
        eq = self.db.get_account_state()["equity"]
        return pnl_sum / eq if eq != 0 else Decimal("0")

    def _consecutive_losses(self) -> int:
        conn = self.db.conn
        rows = conn.execute(
            "SELECT pnl FROM trades ORDER BY exit_time DESC LIMIT ?", (self.max_consecutive_losses,)
        ).fetchall()
        count = 0
        for r in rows:
            if Decimal(r["pnl"]) <= 0:
                count += 1
            else:
                break
        return count

    def check(self) -> bool:
        """Check triggers. Returns True if trading should stop."""
        if self.tripped:
            return True

        # Daily loss
        daily_loss = self._daily_pnl_pct()
        if daily_loss <= -self.max_daily_loss_pct:
            self.tripped = True
            self._liquidate_all("emergency_daily_loss")
            return True

        # Consecutive losses
        if self._consecutive_losses() >= self.max_consecutive_losses:
            self.tripped = True
            self._liquidate_all("emergency_consecutive_losses")
            return True

        return False

    def _liquidate_all(self, reason: str):
        """Close all open positions immediately at last known prices."""
        open_positions = self.position_manager.get_all_open()
        for pair, pos in open_positions.items():
            # use entry price as placeholder; engine should replace with live price fetch in real usage
            exit_price = pos.entry_price
            closed = self.position_manager.close_position(pair, exit_price, reason)
            # cash/equity are updated inside position_manager->paper_trader in engine loop
