"""Diagnostic deep-dive on EMA+RSI strategy.

The standard BacktestEngine discards signal-level indicator data (RSI at entry,
EMA distance, etc.) when it records closed trades.  This script replays the
same candle-by-candle loop but keeps a parallel signal log so we can correlate
every closed trade with the exact indicator state when it was opened.

Analyses:
    1. RSI distribution at signal time (ASCII histogram)
    2. EMA distance at entry (bucketed + win/loss breakdown)
    3. Hold-time distribution (how long positions live before exit)
    4. Win rate vs RSI level at entry (the key "falling knife" detector)

Then prints 3 data-driven modification suggestions.
"""

import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit
from rich.console import Console
from rich.table import Table

import src.engine.backtest as _bt_mod

from src.connectors.alpaca import AlpacaConnector
from src.engine.backtest import BacktestEngine
from src.engine.risk_manager import RiskManager
from src.engine.paper_trader import PaperTrader
from src.engine.position_manager import PositionManager
from src.models.candle import Candle
from src.models.signal import Signal
from src.strategies.ema_rsi import EmaRsiStrategy
from src.data.database import Database

console = Console()
load_dotenv()

# ---------------------------------------------------------------------------
# Config — matches what run_backtest.py uses for EMA_RSI
# ---------------------------------------------------------------------------
PAIRS = ["ETH/USD", "SOL/USD"]
DAYS_BACK = 30
INITIAL_BALANCE = Decimal("1000")

# EMA_RSI params from strategy_params.yaml
STRATEGY_PARAMS = dict(
    rsi_oversold=38,
    rsi_overbought=62,
    min_signal_strength=Decimal("0.6"),
    max_distance_from_ema_pct=0.06,
    atr_period=14,
    atr_multiplier_stop=1.5,
    proximity_pct=0.01,
)

RISK_PARAMS = dict(
    max_positions=5,
    max_position_size_pct=Decimal("0.2"),
    stop_loss_pct=Decimal("0.02"),
    take_profit_pct=Decimal("0.05"),
)


# ---------------------------------------------------------------------------
# Custom replay loop — identical logic to BacktestEngine but captures signals
# ---------------------------------------------------------------------------

def replay_with_signal_capture(
    candles_by_pair: Dict[str, List[Candle]],
    start_date: datetime,
    end_date: datetime,
) -> Tuple[List[Dict], List[Dict]]:
    """Replay backtest, capturing both closed trades and their entry signals.

    Returns:
        (trades, signal_log)
        trades:     same shape as BacktestEngine.trades
        signal_log: list of dicts with signal indicators, keyed linkable by
                    (pair, entry_price) to the matching trade
    """
    strategy = EmaRsiStrategy(**STRATEGY_PARAMS)
    risk_manager = RiskManager(**RISK_PARAMS)

    db = Database(Path(":memory:"))
    paper_trader = PaperTrader(db, INITIAL_BALANCE)
    position_manager = PositionManager(db)

    # Filter to date range
    filtered = {}
    for pair, candles in candles_by_pair.items():
        filtered[pair] = [c for c in candles if start_date <= c.timestamp <= end_date]

    all_timestamps = sorted(set(
        c.timestamp for candles in filtered.values() for c in candles
    ))

    trades: List[Dict] = []
    signal_log: List[Dict] = []
    # Map open positions → their signal data so we can attach it on close
    open_signal_data: Dict[str, Dict] = {}   # pair → signal indicators

    for timestamp in all_timestamps:
        # Build candle window up to this timestamp
        current_candles = {}
        for pair, candles in filtered.items():
            pair_candles = [c for c in candles if c.timestamp <= timestamp]
            if pair_candles:
                current_candles[pair] = pair_candles

        # --- exits first (same order as engine) ---
        for pair, position in list(position_manager.get_all_open().items()):
            if pair not in current_candles:
                continue
            current_price = current_candles[pair][-1].close
            should_close, reason = risk_manager.should_close_position(position, current_price)
            if should_close:
                paper_trader.execute_exit(position, current_price)
                closed = position_manager.close_position(pair, current_price, reason)

                # Hold time from candle timestamps, not wall-clock.
                # Keep _entry_candle_ts in sig_data so the enrichment pass
                # (enrich_with_next_candle_rsi) can look up the next candle.
                sig_data = open_signal_data.pop(pair, {})
                entry_ts = sig_data.get('_entry_candle_ts')
                hold_minutes = (timestamp - entry_ts).total_seconds() / 60 if entry_ts else 0

                trade_record = {
                    'pair': pair,
                    'direction': position.direction.value,
                    'entry_price': float(position.entry_price),
                    'exit_price': float(current_price),
                    'pnl': float(closed.realized_pnl()),
                    'reason': reason,
                    'hold_minutes': hold_minutes,
                    **sig_data,
                }
                trades.append(trade_record)

        # --- entries ---
        for pair, candles in current_candles.items():
            if position_manager.has_position(pair):
                continue

            signal = strategy.analyze(candles)
            if not signal:
                continue

            can_open, _ = risk_manager.can_open_position(
                signal=signal,
                open_positions_count=len(position_manager.get_all_open()),
                has_position_for_pair=False,
            )
            if not can_open:
                continue

            account_value = paper_trader.get_account_value()
            entry_price = candles[-1].close
            quantity = risk_manager.calculate_position_size(account_value, entry_price)
            position = paper_trader.execute_entry(signal, entry_price, quantity)
            position_manager.open_position(position)

            # Capture signal-time indicators for later stitching.
            # _entry_candle_ts is the candle timestamp (not wall-clock) so we
            # can compute real hold-time when the position closes.
            ind = signal.indicators or {}
            captured = {
                'rsi_at_entry': ind.get('rsi'),
                'ema_at_entry': ind.get('ema'),
                'distance_from_ema_pct': ind.get('distance_from_ema_pct'),
                'atr_at_entry': ind.get('atr'),
                'atr_stop': ind.get('atr_stop'),
                'signal_type': signal.signal_type.value,
                '_entry_candle_ts': timestamp,
            }
            open_signal_data[pair] = captured
            signal_log.append({
                'pair': pair,
                'timestamp': timestamp,
                **captured,
            })

    # Close any remaining open positions at end
    final_ts = all_timestamps[-1] if all_timestamps else end_date
    for pair, position in list(position_manager.get_all_open().items()):
        if pair in current_candles and current_candles[pair]:
            current_price = current_candles[pair][-1].close
            paper_trader.execute_exit(position, current_price)
            closed = position_manager.close_position(pair, current_price, "End of backtest")

            sig_data = open_signal_data.pop(pair, {})
            entry_ts = sig_data.get('_entry_candle_ts')
            hold_minutes = (final_ts - entry_ts).total_seconds() / 60 if entry_ts else 0

            trades.append({
                'pair': pair,
                'direction': position.direction.value,
                'entry_price': float(position.entry_price),
                'exit_price': float(current_price),
                'pnl': float(closed.realized_pnl()),
                'reason': "End of backtest",
                'hold_minutes': hold_minutes,
                **sig_data,
            })

    return trades, signal_log


# ---------------------------------------------------------------------------
# Analysis renderers
# ---------------------------------------------------------------------------

def ascii_histogram(values: List[float], bins: int = 10, width: int = 40, label: str = "") -> str:
    """Render a simple ASCII histogram."""
    if not values:
        return "  (no data)"
    lo, hi = min(values), max(values)
    if lo == hi:
        hi = lo + 1  # avoid zero-width bin
    bin_width = (hi - lo) / bins
    counts = [0] * bins
    for v in values:
        idx = min(int((v - lo) / bin_width), bins - 1)
        counts[idx] += 1
    max_count = max(counts) if counts else 1

    lines = []
    for i in range(bins):
        lo_edge = lo + i * bin_width
        hi_edge = lo_edge + bin_width
        bar_len = int((counts[i] / max_count) * width) if max_count > 0 else 0
        bar = "█" * bar_len
        lines.append(f"  {lo_edge:>6.1f}–{hi_edge:<6.1f} │{bar} {counts[i]}")
    return "\n".join(lines)


def print_section(title: str):
    console.print(f"\n[bold cyan]{'─'*60}[/bold cyan]")
    console.print(f"[bold cyan]  {title}[/bold cyan]")
    console.print(f"[bold cyan]{'─'*60}[/bold cyan]\n")


def analysis_1_rsi_distribution(trades: List[Dict]):
    """1. RSI histogram at signal time — where are signals actually firing?"""
    print_section("1. RSI Distribution at Signal Time")

    rsi_values = [t['rsi_at_entry'] for t in trades if t.get('rsi_at_entry') is not None]
    if not rsi_values:
        console.print("  [red]No RSI data captured.[/red]")
        return

    console.print(f"  Signals fired: {len(rsi_values)}")
    console.print(f"  RSI range: {min(rsi_values):.1f} – {max(rsi_values):.1f}")
    console.print(f"  RSI mean:  {sum(rsi_values)/len(rsi_values):.1f}")
    console.print(f"  Configured oversold={STRATEGY_PARAMS['rsi_oversold']}, "
                  f"overbought={STRATEGY_PARAMS['rsi_overbought']}\n")
    console.print(ascii_histogram(rsi_values, bins=8, label="RSI"))
    console.print()


def analysis_2_ema_distance(trades: List[Dict]):
    """2. EMA distance at entry — how far from the mean are we entering?"""
    print_section("2. EMA Distance at Entry (% from EMA)")

    dist_values = [t['distance_from_ema_pct'] for t in trades if t.get('distance_from_ema_pct') is not None]
    if not dist_values:
        console.print("  [red]No distance data captured.[/red]")
        return

    # Bucket into ranges and show win/loss per bucket.
    # Must cover the full max_distance_from_ema_pct range (6%) — the strategy
    # allows entries up to 6% away; trades in the 1.5–6% tail are exactly
    # where "falling knives" hide, so we must not truncate here.
    buckets = [0.0, 0.002, 0.004, 0.006, 0.008, 0.01, 0.02, 0.03, 0.04, 0.06]
    bucket_labels = [
        "0–0.2%", "0.2–0.4%", "0.4–0.6%", "0.6–0.8%", "0.8–1.0%",
        "1.0–2.0%", "2.0–3.0%", "3.0–4.0%", "4.0–6.0%",
    ]

    console.print(f"  Max allowed distance: {STRATEGY_PARAMS['max_distance_from_ema_pct']*100:.1f}%")
    console.print(f"  Proximity gate:       {STRATEGY_PARAMS['proximity_pct']*100:.2f}%")
    console.print(f"  Observed range:       {min(dist_values)*100:.3f}% – {max(dist_values)*100:.3f}%\n")

    table = Table(show_header=True)
    table.add_column("Distance Bucket", style="cyan")
    table.add_column("Trades", justify="right")
    table.add_column("Wins", justify="right", style="green")
    table.add_column("Losses", justify="right", style="red")
    table.add_column("Win Rate", justify="right")
    table.add_column("Avg P&L", justify="right")

    for i in range(len(buckets) - 1):
        lo, hi = buckets[i], buckets[i + 1]
        bucket_trades = [t for t in trades
                         if t.get('distance_from_ema_pct') is not None
                         and lo <= t['distance_from_ema_pct'] < hi]
        if not bucket_trades:
            continue
        wins = [t for t in bucket_trades if t['pnl'] > 0]
        losses = [t for t in bucket_trades if t['pnl'] <= 0]
        wr = len(wins) / len(bucket_trades) * 100
        avg_pnl = sum(t['pnl'] for t in bucket_trades) / len(bucket_trades)
        table.add_row(
            bucket_labels[i],
            str(len(bucket_trades)),
            str(len(wins)),
            str(len(losses)),
            f"{wr:.0f}%",
            f"${avg_pnl:+.2f}",
        )

    console.print(table)
    console.print()


def analysis_3_hold_time(trades: List[Dict]):
    """3. Hold time distribution — are we exiting too fast or too slow?"""
    print_section("3. Position Hold-Time Distribution")

    hold_times = [t['hold_minutes'] for t in trades if t.get('hold_minutes') is not None]
    if not hold_times:
        console.print("  [red]No hold-time data captured.[/red]")
        return

    # Separate winners vs losers
    winner_holds = [t['hold_minutes'] for t in trades if t.get('hold_minutes') and t['pnl'] > 0]
    loser_holds  = [t['hold_minutes'] for t in trades if t.get('hold_minutes') and t['pnl'] <= 0]

    avg_all = sum(hold_times) / len(hold_times)
    avg_w = sum(winner_holds) / len(winner_holds) if winner_holds else 0
    avg_l = sum(loser_holds) / len(loser_holds) if loser_holds else 0

    console.print(f"  All trades  — avg hold: {avg_all:>7.0f} min ({avg_all/60:.1f}h)  "
                  f"| min: {min(hold_times):>6.0f} min | max: {max(hold_times):>7.0f} min")
    console.print(f"  Winners     — avg hold: {avg_w:>7.0f} min ({avg_w/60:.1f}h)")
    console.print(f"  Losers      — avg hold: {avg_l:>7.0f} min ({avg_l/60:.1f}h)\n")

    # Exit-reason breakdown
    reason_counts = defaultdict(lambda: {'n': 0, 'pnl': 0.0})
    for t in trades:
        r = t.get('reason', 'unknown')
        # Normalize the reason text to a short label.
        # Per-signal checks MUST come before the generic stop/take checks
        # because "Per-signal stop loss hit" also contains "stop loss".
        if 'per-signal stop' in r.lower():
            key = 'Stop Loss (ATR signal)'
        elif 'per-signal take' in r.lower():
            key = 'Take Profit (signal → EMA)'
        elif 'stop loss' in r.lower():
            key = 'Stop Loss (risk mgr %)'
        elif 'take profit' in r.lower():
            key = 'Take Profit (risk mgr %)'
        elif 'end of backtest' in r.lower():
            key = 'End of Backtest'
        else:
            key = r
        reason_counts[key]['n'] += 1
        reason_counts[key]['pnl'] += t['pnl']

    table = Table(show_header=True)
    table.add_column("Exit Reason", style="cyan")
    table.add_column("Count", justify="right")
    table.add_column("Total P&L", justify="right")
    table.add_column("Avg P&L", justify="right")

    for reason, stats in sorted(reason_counts.items(), key=lambda x: -x[1]['n']):
        avg = stats['pnl'] / stats['n']
        pnl_style = "green" if stats['pnl'] >= 0 else "red"
        table.add_row(
            reason,
            str(stats['n']),
            f"[{pnl_style}]${stats['pnl']:+.2f}[/{pnl_style}]",
            f"[{pnl_style}]${avg:+.2f}[/{pnl_style}]",
        )

    console.print(table)
    console.print()


def analysis_4_winrate_vs_rsi(trades: List[Dict]):
    """4. Win rate vs RSI at entry — the falling-knife detector."""
    print_section("4. Win Rate vs RSI Level at Entry")

    # Bucket RSI into ranges, show win rate for each
    # For longs: RSI was crossing UP through oversold (so entry RSI is just above threshold)
    # For shorts: RSI was crossing DOWN through overbought

    longs = [t for t in trades if t.get('signal_type') == 'entry_long' and t.get('rsi_at_entry') is not None]
    shorts = [t for t in trades if t.get('signal_type') == 'entry_short' and t.get('rsi_at_entry') is not None]

    for label, subset in [("LONG entries (RSI crossing up through oversold)", longs),
                          ("SHORT entries (RSI crossing down through overbought)", shorts)]:
        if not subset:
            continue

        console.print(f"  [bold]{label}[/bold]")

        rsi_vals = [t['rsi_at_entry'] for t in subset]
        lo, hi = min(rsi_vals), max(rsi_vals)

        # Create buckets across observed range
        n_buckets = min(6, len(subset))  # don't over-bucket sparse data
        if n_buckets < 2:
            # Only one or two trades — just show them directly
            for t in subset:
                won = "WIN" if t['pnl'] > 0 else "LOSS"
                console.print(f"    RSI={t['rsi_at_entry']:.1f}  {won}  P&L=${t['pnl']:+.2f}")
            console.print()
            continue

        bucket_width = (hi - lo) / n_buckets if hi > lo else 1.0
        # Ensure we don't get zero-width buckets
        if bucket_width == 0:
            bucket_width = 1.0

        table = Table(show_header=True)
        table.add_column("RSI Range", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg P&L", justify="right")
        table.add_column("Bar")

        for i in range(n_buckets):
            b_lo = lo + i * bucket_width
            b_hi = b_lo + bucket_width if i < n_buckets - 1 else hi + 0.01
            bucket_trades = [t for t in subset if b_lo <= t['rsi_at_entry'] < b_hi]
            if not bucket_trades:
                continue
            wins = sum(1 for t in bucket_trades if t['pnl'] > 0)
            wr = wins / len(bucket_trades) * 100
            avg_pnl = sum(t['pnl'] for t in bucket_trades) / len(bucket_trades)

            bar_len = int(wr / 100 * 20)
            bar = "█" * bar_len + "░" * (20 - bar_len)
            color = "green" if wr >= 50 else "red"

            table.add_row(
                f"{b_lo:.1f}–{b_hi:.1f}",
                str(len(bucket_trades)),
                f"[{color}]{wr:.0f}%[/{color}]",
                f"${avg_pnl:+.2f}",
                f"[{color}]{bar}[/{color}]",
            )

        console.print(table)
        console.print()


def enrich_with_next_candle_rsi(
    trades: List[Dict],
    candles_by_pair: Dict[str, List[Candle]],
    rsi_period: int = 14,
) -> None:
    """Post-processing pass: for every closed trade, look up the RSI on the
    candle *after* entry and stamp it onto the trade dict.

    This is the key "confirmation" signal.  A genuine reversal will see RSI
    stay above oversold on the next candle.  A falling knife will see RSI
    immediately drop back below.

    Mutates trades in-place (adds 'rsi_next_candle' key).
    """
    import pandas as pd  # local import — already used elsewhere

    # Pre-compute RSI series per pair once
    rsi_by_pair: Dict[str, pd.Series] = {}
    ts_by_pair: Dict[str, List] = {}
    for pair, candles in candles_by_pair.items():
        closes = pd.Series([float(c.close) for c in candles])
        delta = closes.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=rsi_period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=rsi_period).mean()
        rs = gain / loss
        rsi_by_pair[pair] = 100 - (100 / (1 + rs))
        ts_by_pair[pair] = [c.timestamp for c in candles]

    for t in trades:
        pair = t.get('pair')
        entry_ts = t.get('_entry_candle_ts')   # may have been popped; see below
        if not pair or not entry_ts or pair not in ts_by_pair:
            continue
        timestamps = ts_by_pair[pair]
        rsi_series = rsi_by_pair[pair]

        # Find the index of the entry candle
        try:
            idx = timestamps.index(entry_ts)
        except ValueError:
            continue

        # Next candle RSI (if it exists)
        if idx + 1 < len(rsi_series):
            val = rsi_series.iloc[idx + 1]
            t['rsi_next_candle'] = None if pd.isna(val) else float(val)
        else:
            t['rsi_next_candle'] = None


def analysis_5_confirmation(trades: List[Dict]):
    """5. Did RSI hold above oversold on the next candle after entry?

    The strategy fires on a single-candle crossover.  A falling knife will
    show RSI crossing above oversold for exactly one candle before collapsing.
    A real reversal will keep RSI elevated.  This analysis separates the two.
    """
    print_section("5. RSI Confirmation — Did the Cross Hold?")

    oversold = STRATEGY_PARAMS['rsi_oversold']
    overbought = STRATEGY_PARAMS['rsi_overbought']

    # --- LONGS: RSI should stay ABOVE oversold after entry ---
    longs = [t for t in trades
             if t.get('signal_type') == 'entry_long'
             and t.get('rsi_next_candle') is not None]

    if longs:
        confirmed = [t for t in longs if t['rsi_next_candle'] >= oversold]
        faked_out  = [t for t in longs if t['rsi_next_candle'] <  oversold]

        conf_wr  = sum(1 for t in confirmed if t['pnl'] > 0) / len(confirmed) * 100 if confirmed else 0
        fake_wr  = sum(1 for t in faked_out  if t['pnl'] > 0) / len(faked_out)  * 100 if faked_out  else 0
        conf_pnl = sum(t['pnl'] for t in confirmed) / len(confirmed) if confirmed else 0
        fake_pnl = sum(t['pnl'] for t in faked_out)  / len(faked_out)  if faked_out  else 0

        table = Table(show_header=True)
        table.add_column("Long Entry Type", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg P&L", justify="right")
        table.add_column("Description")

        if confirmed:
            color = "green" if conf_wr >= 50 else "red"
            table.add_row(
                "Confirmed",
                str(len(confirmed)),
                f"[{color}]{conf_wr:.0f}%[/{color}]",
                f"${conf_pnl:+.2f}",
                f"RSI stayed ≥ {oversold} next candle",
            )
        if faked_out:
            color = "green" if fake_wr >= 50 else "red"
            table.add_row(
                "Fake-out",
                str(len(faked_out)),
                f"[{color}]{fake_wr:.0f}%[/{color}]",
                f"${fake_pnl:+.2f}",
                f"RSI dropped < {oversold} next candle  ← knives",
            )

        console.print(table)

        if faked_out and confirmed and (conf_wr - fake_wr) >= 15:
            console.print(f"\n  [bold red]Fake-outs are the knife:[/bold red] "
                          f"{len(faked_out)} entries where RSI immediately retreated.")
            console.print(f"  Confirmed entries win {conf_wr:.0f}% vs fake-outs at {fake_wr:.0f}%.")
            console.print(f"  → Add a 1-candle confirmation rule: only enter if RSI stays ≥ {oversold}")
            console.print(f"    on the candle after the crossover.")
        console.print()

    # --- SHORTS: RSI should stay BELOW overbought after entry ---
    shorts = [t for t in trades
              if t.get('signal_type') == 'entry_short'
              and t.get('rsi_next_candle') is not None]

    if shorts:
        confirmed = [t for t in shorts if t['rsi_next_candle'] <= overbought]
        faked_out  = [t for t in shorts if t['rsi_next_candle'] >  overbought]

        conf_wr  = sum(1 for t in confirmed if t['pnl'] > 0) / len(confirmed) * 100 if confirmed else 0
        fake_wr  = sum(1 for t in faked_out  if t['pnl'] > 0) / len(faked_out)  * 100 if faked_out  else 0
        conf_pnl = sum(t['pnl'] for t in confirmed) / len(confirmed) if confirmed else 0
        fake_pnl = sum(t['pnl'] for t in faked_out)  / len(faked_out)  if faked_out  else 0

        table = Table(show_header=True)
        table.add_column("Short Entry Type", style="cyan")
        table.add_column("Trades", justify="right")
        table.add_column("Win Rate", justify="right")
        table.add_column("Avg P&L", justify="right")
        table.add_column("Description")

        if confirmed:
            color = "green" if conf_wr >= 50 else "red"
            table.add_row(
                "Confirmed",
                str(len(confirmed)),
                f"[{color}]{conf_wr:.0f}%[/{color}]",
                f"${conf_pnl:+.2f}",
                f"RSI stayed ≤ {overbought} next candle",
            )
        if faked_out:
            color = "green" if fake_wr >= 50 else "red"
            table.add_row(
                "Fake-out",
                str(len(faked_out)),
                f"[{color}]{fake_wr:.0f}%[/{color}]",
                f"${fake_pnl:+.2f}",
                f"RSI bounced > {overbought} next candle  ← knives",
            )

        console.print(table)

        if faked_out and confirmed and (conf_wr - fake_wr) >= 15:
            console.print(f"\n  [bold red]Fake-outs are the knife:[/bold red] "
                          f"{len(faked_out)} entries where RSI immediately bounced back.")
            console.print(f"  Confirmed entries win {conf_wr:.0f}% vs fake-outs at {fake_wr:.0f}%.")
            console.print(f"  → Add a 1-candle confirmation rule: only enter if RSI stays ≤ {overbought}")
            console.print(f"    on the candle after the crossover.")
        console.print()

    if not longs and not shorts:
        console.print("  [red]No next-candle RSI data available.[/red]\n")


def print_suggestions(trades: List[Dict]):
    """Print 3 data-driven modification suggestions."""
    print_section("SUGGESTED MODIFICATIONS")

    # Gather the data we need for suggestions
    longs = [t for t in trades if t.get('signal_type') == 'entry_long']
    shorts = [t for t in trades if t.get('signal_type') == 'entry_short']
    all_rsi = [t['rsi_at_entry'] for t in trades if t.get('rsi_at_entry') is not None]
    all_dist = [t['distance_from_ema_pct'] for t in trades if t.get('distance_from_ema_pct') is not None]

    # Bucket long entries by RSI at entry (same granularity as analysis_4)
    # and find the best / worst buckets so the suggestion is grounded in
    # the same data the user just saw in the table above.
    long_rsi = [t['rsi_at_entry'] for t in longs if t.get('rsi_at_entry')]
    rsi_buckets: List[Tuple] = []   # (lo, hi, win_rate, n_trades)
    if long_rsi:
        lo_rsi, hi_rsi = min(long_rsi), max(long_rsi)
        n_buckets = min(6, len(long_rsi))
        bw = (hi_rsi - lo_rsi) / n_buckets if hi_rsi > lo_rsi else 1.0
        if bw == 0:
            bw = 1.0
        for i in range(n_buckets):
            b_lo = lo_rsi + i * bw
            b_hi = b_lo + bw if i < n_buckets - 1 else hi_rsi + 0.01
            bt = [t for t in longs if t.get('rsi_at_entry') and b_lo <= t['rsi_at_entry'] < b_hi]
            if len(bt) < 2:
                continue
            wr = sum(1 for t in bt if t['pnl'] > 0) / len(bt) * 100
            rsi_buckets.append((b_lo, b_hi, wr, len(bt)))

    # Hold time comparison
    winner_holds = [t['hold_minutes'] for t in trades if t['pnl'] > 0 and t.get('hold_minutes')]
    loser_holds = [t['hold_minutes'] for t in trades if t['pnl'] <= 0 and t.get('hold_minutes')]
    avg_winner_hold = sum(winner_holds) / len(winner_holds) if winner_holds else 0
    avg_loser_hold = sum(loser_holds) / len(loser_holds) if loser_holds else 0

    # Stop-loss hit rate
    sl_hits = [t for t in trades if 'stop' in t.get('reason', '').lower()]
    tp_hits = [t for t in trades if 'take profit' in t.get('reason', '').lower()]
    eob_hits = [t for t in trades if 'end of backtest' in t.get('reason', '').lower()]

    # ---------------------------------------------------------------------------
    # Suggestion 1: RSI threshold
    # ---------------------------------------------------------------------------
    console.print("[bold green]1. RSI Threshold Adjustment[/bold green]")
    if len(rsi_buckets) >= 2:
        best_rsi  = max(rsi_buckets, key=lambda b: b[2])   # highest win rate
        worst_rsi = min(rsi_buckets, key=lambda b: b[2])   # lowest win rate
        gap_pp = best_rsi[2] - worst_rsi[2]                # percentage-point gap

        console.print(f"   Best  RSI bucket: {best_rsi[0]:.1f}–{best_rsi[1]:.1f}  →  "
                      f"{best_rsi[2]:.0f}% win rate ({best_rsi[3]} trades)")
        console.print(f"   Worst RSI bucket: {worst_rsi[0]:.1f}–{worst_rsi[1]:.1f}  →  "
                      f"{worst_rsi[2]:.0f}% win rate ({worst_rsi[3]} trades)")

        if gap_pp >= 20:
            # Meaningful gap — recommend tightening to the best bucket.
            # The best bucket's lower edge is the new oversold threshold: RSI
            # must cross *that* level (higher confirmation) before we enter.
            new_threshold = int(round(best_rsi[0]))
            console.print(f"   {gap_pp:.0f}pp gap between best and worst buckets.")
            console.print(f"   → Raise rsi_oversold from {STRATEGY_PARAMS['rsi_oversold']} to ~{new_threshold}")
            console.print(f"     (only enter when RSI crosses into the {best_rsi[0]:.1f}+ sweet spot)")
        else:
            console.print(f"   Gap is only {gap_pp:.0f}pp — RSI level alone isn't decisive.")
            console.print(f"   Current oversold={STRATEGY_PARAMS['rsi_oversold']} is fine; look at filters 2 & 3.")
    else:
        console.print("   Insufficient long-trade data to bucket RSI meaningfully.")
        console.print(f"   Current oversold={STRATEGY_PARAMS['rsi_oversold']} — keep and gather more data.")
    console.print()

    # ---------------------------------------------------------------------------
    # Suggestion 2: EMA distance filter
    # ---------------------------------------------------------------------------
    console.print("[bold green]2. EMA Distance Filter[/bold green]")
    if all_dist:
        # Use the same buckets as analysis_2 to find best and worst buckets
        buckets = [0.0, 0.002, 0.004, 0.006, 0.008, 0.01, 0.02, 0.03, 0.04, 0.06]
        best_bucket = None   # (label, lo, hi, win_rate, n_trades)
        worst_bucket = None

        for i in range(len(buckets) - 1):
            lo, hi = buckets[i], buckets[i + 1]
            bt = [t for t in trades
                  if t.get('distance_from_ema_pct') is not None
                  and lo <= t['distance_from_ema_pct'] < hi]
            if len(bt) < 2:   # skip buckets too sparse to be meaningful
                continue
            wr = sum(1 for t in bt if t['pnl'] > 0) / len(bt) * 100
            entry = (f"{lo*100:.1f}–{hi*100:.1f}%", lo, hi, wr, len(bt))
            if best_bucket is None or wr > best_bucket[3]:
                best_bucket = entry
            if worst_bucket is None or wr < worst_bucket[3]:
                worst_bucket = entry

        console.print(f"   Observed distance range: {min(all_dist)*100:.3f}% – {max(all_dist)*100:.3f}%")
        if best_bucket and worst_bucket:
            console.print(f"   Best bucket:  {best_bucket[0]} — {best_bucket[3]:.0f}% win rate ({best_bucket[4]} trades)")
            console.print(f"   Worst bucket: {worst_bucket[0]} — {worst_bucket[3]:.0f}% win rate ({worst_bucket[4]} trades)")

            if best_bucket[3] - worst_bucket[3] >= 20:
                # Significant gap — recommend narrowing to the best bucket's range
                # Set proximity_pct to the upper edge of the best bucket
                new_prox = best_bucket[2]
                # But also add a minimum-distance floor at the best bucket's lower edge
                min_dist = best_bucket[1]
                console.print(f"   → Set proximity_pct to {new_prox} (upper edge of best bucket)")
                if min_dist > 0:
                    console.print(f"     AND add a min_distance_from_ema_pct = {min_dist}")
                    console.print(f"     (skip entries that are TOO close — they're noise, not dislocations)")
                else:
                    console.print(f"     (only accept entries within the {best_bucket[0]} sweet spot)")
            else:
                console.print(f"   → Buckets are within {best_bucket[3] - worst_bucket[3]:.0f}pp of each other.")
                console.print(f"     Current proximity_pct={STRATEGY_PARAMS['proximity_pct']} is fine.")
        else:
            console.print("   Not enough data per bucket to compare.")
    else:
        console.print("   No distance data available.")
    console.print()

    # ---------------------------------------------------------------------------
    # Suggestion 3: Exit timing
    # ---------------------------------------------------------------------------
    console.print("[bold green]3. Exit Timing Improvements[/bold green]")
    console.print(f"   Winners hold avg {avg_winner_hold:.0f} min ({avg_winner_hold/60:.1f}h)")
    console.print(f"   Losers  hold avg {avg_loser_hold:.0f} min ({avg_loser_hold/60:.1f}h)")
    console.print(f"   Stop-loss exits: {len(sl_hits)}  |  Take-profit exits: {len(tp_hits)}  |  End-of-backtest: {len(eob_hits)}")

    if avg_loser_hold > avg_winner_hold:
        console.print(f"   Losers are held LONGER than winners ({avg_loser_hold:.0f} vs {avg_winner_hold:.0f} min).")
        console.print(f"   The ATR stop at {STRATEGY_PARAMS['atr_multiplier_stop']}x is too wide — losers drift")
        console.print(f"   for a long time before hitting it.")
        new_mult = round(STRATEGY_PARAMS['atr_multiplier_stop'] * 0.7, 2)
        console.print(f"   → Reduce atr_multiplier_stop from {STRATEGY_PARAMS['atr_multiplier_stop']} to ~{new_mult}")
        console.print(f"     (cut losers faster; winners exit via take-profit anyway)")
    elif avg_winner_hold > avg_loser_hold:
        console.print(f"   Winners are held longer ({avg_winner_hold:.0f} vs {avg_loser_hold:.0f} min).")
        console.print(f"   Stops are cutting out quickly — that's fine, but take-profit may be too tight.")
        console.print(f"   → Current take_profit targets EMA (correct for mean reversion).")
        console.print(f"     Consider adding a trailing stop after price crosses EMA to capture overshoots.")
    else:
        console.print(f"   Hold times are similar. Exit timing is not the primary issue.")

    if eob_hits:
        console.print(f"\n   WARNING: {len(eob_hits)} trade(s) survived to end-of-backtest without hitting")
        console.print(f"   stop or take-profit. These are the most dangerous — add a max-hold-time")
        console.print(f"   rule (e.g. force-close after 4h) to prevent open-ended exposure.")
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    console.print("\n[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]")
    console.print("[bold cyan]   EMA+RSI STRATEGY DIAGNOSTIC[/bold cyan]")
    console.print("[bold cyan]══════════════════════════════════════════════════════════[/bold cyan]\n")

    console.print("[bold]Downloading candle data...[/bold]")
    alpaca = AlpacaConnector(
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        paper=True,
    )
    candles_by_pair = alpaca.fetch_recent_candles(
        pairs=PAIRS,
        timeframe=TimeFrame(15, TimeFrameUnit.Minute),
        limit=3000,
    )
    for pair, candles in candles_by_pair.items():
        console.print(f"  {pair}: {len(candles)} candles")

    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=DAYS_BACK)

    console.print("\n[bold]Replaying backtest with signal capture...[/bold]")
    trades, signal_log = replay_with_signal_capture(candles_by_pair, start_date, end_date)

    if not trades:
        console.print("[red]No trades were taken. Nothing to diagnose.[/red]")
        return

    # Summary header
    winners = [t for t in trades if t['pnl'] > 0]
    total_pnl = sum(t['pnl'] for t in trades)
    console.print(f"\n  Total trades: {len(trades)}  |  "
                  f"Winners: {len(winners)}  |  "
                  f"Win rate: {len(winners)/len(trades)*100:.1f}%  |  "
                  f"Total P&L: ${total_pnl:+.2f}\n")

    # Enrich trades with next-candle RSI before running analyses
    enrich_with_next_candle_rsi(trades, candles_by_pair)

    # Run all five analyses
    analysis_1_rsi_distribution(trades)
    analysis_2_ema_distance(trades)
    analysis_3_hold_time(trades)
    analysis_4_winrate_vs_rsi(trades)
    analysis_5_confirmation(trades)

    # Print suggestions
    print_suggestions(trades)


if __name__ == "__main__":
    main()
