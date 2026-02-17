"""CLI P&L reporting tool for Stonkers trading bot.

Usage:
    python -m src.reports --days 7
    python -m src.reports --days 30 --db data/stonkers.db
"""
import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from rich.console import Console
from rich.table import Table

from src.data.database import Database

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Stonkers P&L Reports")
    parser.add_argument("--db", default="data/stonkers.db", help="Database path")
    parser.add_argument("--days", type=int, default=7, help="Lookback period in days")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        console.print(f"[red]Database not found: {db_path}[/red]")
        return

    db = Database(db_path)
    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    console.print(f"\n[bold cyan]Stonkers P&L Report[/bold cyan]")
    console.print(f"Period: last {args.days} days (since {since.strftime('%Y-%m-%d')})\n")

    _print_overall_summary(db, since)
    _print_strategy_breakdown(db, since)
    _print_drawdown(db, since)
    _print_recent_trades(db, limit=20)
    _print_equity_trend(db, since)

    db.close()


def _print_overall_summary(db: Database, since: datetime) -> None:
    """Print overall P&L summary."""
    trades = db.get_trades_by_strategy(since=since)

    if not trades:
        console.print("[dim]No trades in this period.[/dim]\n")
        return

    total_pnl = sum(t["pnl"] for t in trades)
    winners = [t for t in trades if t["pnl"] > 0]
    losers = [t for t in trades if t["pnl"] <= 0]
    win_rate = (len(winners) / len(trades)) * 100 if trades else 0

    gross_profit = sum(t["pnl"] for t in winners)
    gross_loss = abs(sum(t["pnl"] for t in losers))
    profit_factor = float(gross_profit / gross_loss) if gross_loss > 0 else float("inf")

    avg_win = gross_profit / len(winners) if winners else Decimal("0")
    avg_loss = sum(t["pnl"] for t in losers) / len(losers) if losers else Decimal("0")

    table = Table(title="Overall Summary")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="white")

    pnl_style = "green" if total_pnl >= 0 else "red"
    table.add_row("Total P&L", f"[{pnl_style}]${total_pnl:+.2f}[/{pnl_style}]")
    table.add_row("Total Trades", str(len(trades)))
    table.add_row("Winners / Losers", f"{len(winners)} / {len(losers)}")
    table.add_row("Win Rate", f"{win_rate:.1f}%")
    table.add_row("Profit Factor", f"{profit_factor:.2f}")
    table.add_row("Avg Win", f"${avg_win:+.2f}")
    table.add_row("Avg Loss", f"${avg_loss:+.2f}")

    console.print(table)
    console.print()


def _print_strategy_breakdown(db: Database, since: datetime) -> None:
    """Print per-strategy P&L breakdown."""
    trades = db.get_trades_by_strategy(since=since)
    if not trades:
        return

    stats = defaultdict(lambda: {"trades": 0, "winners": 0, "pnl": Decimal("0"),
                                   "gross_win": Decimal("0"), "gross_loss": Decimal("0")})

    for t in trades:
        s = stats[t["strategy_name"]]
        s["trades"] += 1
        s["pnl"] += t["pnl"]
        if t["pnl"] > 0:
            s["winners"] += 1
            s["gross_win"] += t["pnl"]
        else:
            s["gross_loss"] += abs(t["pnl"])

    table = Table(title="Per-Strategy Breakdown")
    table.add_column("Strategy", style="cyan")
    table.add_column("Trades")
    table.add_column("Win Rate")
    table.add_column("P&L")
    table.add_column("Profit Factor")

    for name, s in sorted(stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        wr = (s["winners"] / s["trades"]) * 100 if s["trades"] > 0 else 0
        pf = float(s["gross_win"] / s["gross_loss"]) if s["gross_loss"] > 0 else float("inf")
        pnl_style = "green" if s["pnl"] >= 0 else "red"
        table.add_row(
            name,
            str(s["trades"]),
            f"{wr:.1f}%",
            f"[{pnl_style}]${s['pnl']:+.2f}[/{pnl_style}]",
            f"{pf:.2f}",
        )

    console.print(table)
    console.print()


def _print_drawdown(db: Database, since: datetime) -> None:
    """Print drawdown from equity snapshots."""
    snapshots = db.get_equity_snapshots(since=since)
    if not snapshots:
        console.print("[dim]No equity snapshots available for drawdown calculation.[/dim]\n")
        return

    peak = Decimal("0")
    max_dd = Decimal("0")
    current_dd = Decimal("0")

    for snap in snapshots:
        equity = snap["equity"]
        if equity > peak:
            peak = equity
        if peak > 0:
            dd = (peak - equity) / peak
            if dd > max_dd:
                max_dd = dd
            current_dd = dd

    latest = snapshots[-1]
    console.print(f"[bold]Drawdown[/bold]")
    console.print(f"  Current equity: ${latest['equity']:.2f}")
    console.print(f"  Peak equity:    ${peak:.2f}")
    console.print(f"  Current DD:     {current_dd:.2%}")
    console.print(f"  Max DD:         {max_dd:.2%}")
    console.print()


def _print_recent_trades(db: Database, limit: int = 20) -> None:
    """Print recent trades."""
    trades = db.get_recent_trades(limit=limit)
    if not trades:
        console.print("[dim]No recent trades.[/dim]\n")
        return

    table = Table(title=f"Recent Trades (last {limit})")
    table.add_column("Pair")
    table.add_column("Dir")
    table.add_column("P&L")
    table.add_column("P&L %")
    table.add_column("Time")

    for t in trades:
        pnl_style = "green" if t["pnl"] >= 0 else "red"
        table.add_row(
            t["pair"],
            t["direction"].upper(),
            f"[{pnl_style}]${t['pnl']:+.2f}[/{pnl_style}]",
            f"{t['pnl_pct']:+.1f}%",
            t["exit_time"][:16] if t["exit_time"] else "",
        )

    console.print(table)
    console.print()


def _print_equity_trend(db: Database, since: datetime) -> None:
    """Print equity trend as a text sparkline."""
    snapshots = db.get_equity_snapshots(since=since, limit=500)
    if len(snapshots) < 2:
        return

    equities = [float(s["equity"]) for s in snapshots]
    min_eq = min(equities)
    max_eq = max(equities)
    eq_range = max_eq - min_eq

    if eq_range == 0:
        console.print("[dim]Equity flat — no trend to display.[/dim]\n")
        return

    # Downsample to ~60 characters
    step = max(1, len(equities) // 60)
    sampled = equities[::step]

    blocks = " _.,:-=!#"
    sparkline = ""
    for val in sampled:
        idx = int((val - min_eq) / eq_range * (len(blocks) - 1))
        sparkline += blocks[idx]

    first = equities[0]
    last = equities[-1]
    change = last - first
    pct = (change / first) * 100 if first > 0 else 0
    style = "green" if change >= 0 else "red"

    console.print(f"[bold]Equity Trend[/bold] (${first:.0f} -> ${last:.0f}, [{style}]{pct:+.1f}%[/{style}])")
    console.print(f"  {sparkline}")
    console.print()


if __name__ == "__main__":
    main()
