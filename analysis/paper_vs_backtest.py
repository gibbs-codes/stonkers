"""Compare backtest vs paper trading performance using logs."""
from pathlib import Path
from decimal import Decimal
import pandas as pd

from src.data.database import Database


def load_trades(db: Database):
    df = pd.read_sql_query("SELECT * FROM trades", db.conn)
    if df.empty:
        return df
    df["pnl"] = df["pnl"].astype(float)
    df["entry_time"] = pd.to_datetime(df["entry_time"])
    df["exit_time"] = pd.to_datetime(df["exit_time"])
    return df


def load_signals(db: Database):
    df = pd.read_sql_query("SELECT * FROM signal_logs", db.conn)
    if df.empty:
        return df
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def summarize_paper(df_trades: pd.DataFrame):
    if df_trades.empty:
        return {}
    summary = df_trades.groupby("strategy_name").agg(
        trades=("id", "count"),
        winners=("pnl", lambda s: (s > 0).sum()),
        losers=("pnl", lambda s: (s <= 0).sum()),
        pnl_total=("pnl", "sum"),
        max_dd=("pnl", lambda s: 0),  # placeholder; more involved calc omitted
    )
    summary["win_rate"] = (summary["winners"] / summary["trades"]) * 100
    return summary


def main():
    db = Database()
    trades = load_trades(db)
    signals = load_signals(db)

    paper_summary = summarize_paper(trades)

    lines = []
    lines.append("# Paper vs Backtest Validation")
    if trades.empty:
        lines.append("No paper trades logged yet. Run paper trading for at least two weeks.")
    else:
        lines.append("## Paper Trading Summary")
        lines.append(paper_summary.to_markdown())

    out = Path("analysis/paper_validation_report.md")
    out.write_text("\n\n".join(lines))
    print("Wrote", out)


if __name__ == "__main__":
    main()
