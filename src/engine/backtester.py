"""Lightweight bar-by-bar backtester with slippage and commission."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, date
from decimal import Decimal
from typing import Dict, Iterable, List, Optional
import uuid

from src.models.candle import Candle
from src.models.position import Direction, Position
from src.models.signal import Signal
from src.engine.risk_manager import RiskManager


@dataclass
class BacktestTrade:
    """Simple trade record for backtest outputs."""

    pair: str
    strategy: str
    direction: Direction
    entry_time: datetime
    exit_time: datetime
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    pnl: Decimal
    fees: Decimal
    reason: str


class Backtester:
    """Bar-by-bar backtester that simulates realistic fills.

    Responsibilities:
    - Iterate historical candles without lookahead
    - Ask each strategy for signals using data up to current bar
    - Apply slippage + commission on fills
    - Respect RiskManager constraints (max positions, sizing)
    - Track equity curve and executed trades
    """

    def __init__(
        self,
        strategies: List,
        risk_manager: RiskManager,
        initial_equity: Decimal = Decimal("10000"),
        slippage_pct: Decimal = Decimal("0.0005"),  # 5 bps
        commission_pct: Decimal = Decimal("0.0004"),  # 4 bps each side
        max_daily_loss_pct: Decimal = Decimal("0.05"),
    ) -> None:
        self.strategies = strategies
        self.risk = risk_manager
        self.initial_equity = initial_equity
        self.slippage_pct = slippage_pct
        self.commission_pct = commission_pct
        self.max_daily_loss_pct = max_daily_loss_pct

        self.trades: List[BacktestTrade] = []
        self.equity_curve: List[Dict] = []

    # Public API -----------------------------------------------------------------
    def run(
        self,
        candles_by_pair: Dict[str, List[Candle]],
        start: Optional[datetime] = None,
        end: Optional[datetime] = None,
    ) -> Dict:
        """Run the backtest.

        Args:
            candles_by_pair: Dict of pair -> ordered list of Candle (oldest first)
            start: Optional start datetime filter
            end: Optional end datetime filter

        Returns:
            Dict with trades, equity_curve, final_equity, total_return_pct, total_trades
        """

        filtered = {pair: self._filter_candles(c, start, end) for pair, c in candles_by_pair.items()}
        if not any(filtered.values()):
            return {"trades": [], "equity_curve": [], "final_equity": self.initial_equity, "total_return_pct": Decimal("0"), "total_trades": 0}

        timestamps = sorted({c.timestamp for candles in filtered.values() for c in candles})
        positions: Dict[str, Position] = {}
        cash = self.initial_equity

        # State for daily loss halting
        current_day: Optional[date] = None
        start_day_equity: Decimal = cash
        trading_halted = False

        # Pointers to avoid repeated slicing
        idx: Dict[str, int] = {p: 0 for p in filtered}
        last_candle: Dict[str, Optional[Candle]] = {p: None for p in filtered}

        for ts in timestamps:
            # Advance candles up to ts for each pair
            for pair, candles in filtered.items():
                while idx[pair] < len(candles) and candles[idx[pair]].timestamp <= ts:
                    last_candle[pair] = candles[idx[pair]]
                    idx[pair] += 1

            # Day change handling
            ts_day = ts.date()
            if current_day != ts_day:
                current_day = ts_day
                start_day_equity = self._current_equity(cash, positions, last_candle)
                trading_halted = False

            # Exits first (risk)
            for pair, position in list(positions.items()):
                candle = last_candle.get(pair)
                if not candle:
                    continue

                should_close, reason = self.risk.should_close_position(position, candle.close)
                if should_close:
                    cash, closed = self._close_position(position, candle.close, cash, reason)
                    positions.pop(pair)
                    self.trades.append(closed)

            # Update equity after exits
            equity = self._current_equity(cash, positions, last_candle)

            # Daily loss check
            if self.max_daily_loss_pct > 0:
                loss_pct = (start_day_equity - equity) / start_day_equity if start_day_equity > 0 else Decimal("0")
                if loss_pct >= self.max_daily_loss_pct:
                    trading_halted = True

            # Entries
            if not trading_halted:
                for pair, candles in filtered.items():
                    if self.risk.max_positions and len(positions) >= self.risk.max_positions:
                        break

                    if pair in positions:
                        continue

                    history = candles[: idx[pair]]  # up to current bar (inclusive)
                    if not history:
                        continue

                    for strategy in self.strategies:
                        signal: Optional[Signal] = strategy.analyze(history)
                        if not signal:
                            continue

                        can_open, reason = self.risk.can_open_position(
                            signal=signal,
                            open_positions_count=len(positions),
                            has_position_for_pair=False,
                        )
                        if not can_open:
                            continue

                        fill_price = self._apply_slippage(history[-1].close, signal)
                        qty = self.risk.calculate_position_size(Decimal(equity), fill_price)

                        # Cash check
                        entry_notional = fill_price * qty
                        fee_entry = entry_notional * self.commission_pct

                        if signal.is_long and cash < entry_notional + fee_entry:
                            continue  # insufficient funds for long

                        position_id = f"pos_{uuid.uuid4().hex[:8]}"
                        entry_time = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)

                        position = Position(
                            id=position_id,
                            pair=pair,
                            direction=Direction.LONG if signal.is_long else Direction.SHORT,
                            entry_price=fill_price,
                            quantity=qty,
                            entry_time=entry_time,
                            strategy_name=signal.strategy_name,
                            stop_loss_price=signal.stop_loss_price,
                            take_profit_price=signal.take_profit_price,
                        )

                        # Apply cash movements
                        if signal.is_long:
                            cash -= entry_notional + fee_entry
                        else:
                            cash += entry_notional - fee_entry  # short: receive proceeds now

                        positions[pair] = position
                        break  # one strategy per pair per bar

            # Record equity after entries
            equity = self._current_equity(cash, positions, last_candle)
            self.equity_curve.append({"timestamp": ts, "equity": equity})

        # Close any remaining positions at final seen price
        final_ts = timestamps[-1] if timestamps else datetime.now(timezone.utc)
        for pair, position in list(positions.items()):
            candle = last_candle.get(pair)
            if not candle:
                continue
            cash, closed = self._close_position(position, candle.close, cash, "End of data")
            self.trades.append(closed)
            positions.pop(pair, None)

        final_equity = self._current_equity(cash, positions, last_candle)
        total_return_pct = (final_equity - self.initial_equity) / self.initial_equity * Decimal("100") if self.initial_equity else Decimal("0")

        return {
            "trades": self.trades,
            "equity_curve": self.equity_curve,
            "final_equity": final_equity,
            "total_return_pct": total_return_pct,
            "total_trades": len(self.trades),
        }

    # Internals ------------------------------------------------------------------
    def _filter_candles(
        self,
        candles: List[Candle],
        start: Optional[datetime],
        end: Optional[datetime],
    ) -> List[Candle]:
        out = []
        for c in candles:
            if start and c.timestamp < start:
                continue
            if end and c.timestamp > end:
                continue
            out.append(c)
        return sorted(out, key=lambda c: c.timestamp)

    def _apply_slippage(self, price: Decimal, signal: Signal | Position) -> Decimal:
        # Long entries/exits pay worse price, shorts get slightly better on entry but worse on buy-back
        if isinstance(signal, Signal):
            is_long = signal.is_long
        else:
            is_long = signal.direction == Direction.LONG

        if is_long:
            return price * (Decimal("1") + self.slippage_pct)
        return price * (Decimal("1") - self.slippage_pct)

    def _close_position(
        self,
        position: Position,
        market_price: Decimal,
        cash: Decimal,
        reason: str,
    ) -> tuple[Decimal, BacktestTrade]:
        fill_price = self._apply_slippage(market_price, position)
        notional_exit = fill_price * position.quantity
        fee_exit = notional_exit * self.commission_pct
        fee_entry = position.entry_price * position.quantity * self.commission_pct
        total_fees = fee_entry + fee_exit

        if position.direction == Direction.LONG:
            cash += notional_exit - fee_exit
            pnl = (fill_price - position.entry_price) * position.quantity - total_fees
        else:
            cash -= notional_exit + fee_exit  # buy back borrowed asset
            pnl = (position.entry_price - fill_price) * position.quantity - total_fees

        closed = BacktestTrade(
            pair=position.pair,
            strategy=position.strategy_name,
            direction=position.direction,
            entry_time=position.entry_time,
            exit_time=datetime.now(timezone.utc),
            entry_price=position.entry_price,
            exit_price=fill_price,
            quantity=position.quantity,
            pnl=pnl,
            fees=total_fees,
            reason=reason,
        )

        return cash, closed

    def _current_equity(
        self,
        cash: Decimal,
        positions: Dict[str, Position],
        last_candle: Dict[str, Optional[Candle]],
    ) -> Decimal:
        unrealized = Decimal("0")
        for pair, position in positions.items():
            candle = last_candle.get(pair)
            if candle:
                price = candle.close
                unrealized += position.unrealized_pnl(price)
        return cash + unrealized

