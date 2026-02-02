"""Backtest visualization utilities (matplotlib, publication-ready)."""
from __future__ import annotations

import matplotlib

# Headless rendering for CLI/servers
matplotlib.use("Agg")

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from pathlib import Path
from typing import Dict, Iterable, List, Optional


class BacktestVisualizer:
    """Generate charts for backtest results (equity, drawdown, trades, calendar)."""

    def __init__(self, output_dir: Path | str = Path("artifacts/backtests")):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        plt.style.use("seaborn-v0_8")

    # --------------------------------------------------------------------- helpers
    def _to_frame(self, equity_curve: Iterable[dict]) -> pd.DataFrame:
        df = pd.DataFrame(equity_curve)
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp")
        return df

    def _drawdown_series(self, df: pd.DataFrame) -> pd.Series:
        if df.empty:
            return pd.Series(dtype=float)
        equity = df["equity"].astype(float)
        peaks = equity.cummax()
        dd = (equity - peaks) / peaks
        return dd

    def _trades_frame(self, trades: Iterable) -> pd.DataFrame:
        df = pd.DataFrame(trades)
        if df.empty:
            return df
        if "pnl" in df.columns:
            df["pnl"] = pd.to_numeric(df["pnl"])
        df["exit_time"] = pd.to_datetime(df.get("exit_time", df.get("timestamp")))
        return df

    # ------------------------------------------------------------------ public API
    def plot_equity_curves(self, curves: Dict[str, Iterable[dict]], title: str = "Equity Curve") -> Path:
        fig, ax = plt.subplots(figsize=(10, 5))
        for name, curve in curves.items():
            df = self._to_frame(curve)
            if df.empty:
                continue
            ax.plot(df["timestamp"], df["equity"], label=name, linewidth=1.6)
        ax.set_title(title)
        ax.set_xlabel("Time")
        ax.set_ylabel("Equity")
        ax.legend()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
        out = self.output_dir / f"equity_curve.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        return out

    def plot_drawdowns(self, curves: Dict[str, Iterable[dict]], title: str = "Drawdown") -> Path:
        fig, ax = plt.subplots(figsize=(10, 4))
        for name, curve in curves.items():
            df = self._to_frame(curve)
            dd = self._drawdown_series(df)
            if dd.empty:
                continue
            ax.fill_between(df["timestamp"], dd * 100, step="mid", alpha=0.3, label=name)
        ax.set_title(title)
        ax.set_ylabel("Drawdown (%)")
        ax.set_xlabel("Time")
        ax.legend()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate()
        out = self.output_dir / "drawdown.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        return out

    def plot_trade_histogram(self, trades_by_strategy: Dict[str, Iterable], bins: int = 30, title: str = "Trade P&L Distribution") -> Path:
        fig, ax = plt.subplots(figsize=(8, 5))
        for name, trades in trades_by_strategy.items():
            df = self._trades_frame(trades)
            if df.empty:
                continue
            ax.hist(df["pnl"], bins=bins, alpha=0.4, label=name)
        ax.set_title(title)
        ax.set_xlabel("Trade P&L")
        ax.set_ylabel("Frequency")
        ax.legend()
        out = self.output_dir / "trade_distribution.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        return out

    def plot_calendar_heatmap(self, trades: Iterable, strategy_name: str, title: Optional[str] = None) -> Path:
        df = self._trades_frame(trades)
        if df.empty:
            # create empty placeholder plot
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.text(0.5, 0.5, "No trades", ha="center", va="center")
            ax.axis("off")
            out = self.output_dir / f"{strategy_name}_calendar.png"
            fig.savefig(out, dpi=150)
            plt.close(fig)
            return out

        df["date"] = df["exit_time"].dt.date
        daily_pnl = df.groupby("date")["pnl"].sum()
        calendar = daily_pnl.reset_index()
        calendar["date"] = pd.to_datetime(calendar["date"])
        calendar["week"] = calendar["date"].dt.isocalendar().week
        calendar["dow"] = calendar["date"].dt.dayofweek
        pivot = calendar.pivot(index="dow", columns="week", values="pnl").sort_index(ascending=False)

        fig, ax = plt.subplots(figsize=(12, 3))
        c = ax.imshow(pivot, aspect="auto", cmap="RdYlGn", interpolation="nearest")
        ax.set_yticks(range(7))
        ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][::-1])
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns)
        ax.set_xlabel("ISO Week")
        ax.set_title(title or f"{strategy_name} Win/Loss Calendar")
        fig.colorbar(c, ax=ax, label="Daily P&L")
        out = self.output_dir / f"{strategy_name}_calendar.png"
        fig.tight_layout()
        fig.savefig(out, dpi=150)
        plt.close(fig)
        return out

    def plot_dashboard(
        self,
        strategy_name: str,
        equity_curve: Iterable[dict],
        trades: Iterable,
        comparison_curves: Optional[Dict[str, Iterable[dict]]] = None,
    ) -> Path:
        """4-panel dashboard: equity, drawdown, histogram, calendar."""
        fig, axes = plt.subplots(2, 2, figsize=(14, 9))

        # Equity
        ax = axes[0, 0]
        primary_df = self._to_frame(equity_curve)
        if not primary_df.empty:
            ax.plot(primary_df["timestamp"], primary_df["equity"], label=strategy_name, linewidth=1.6)
        if comparison_curves:
            for name, curve in comparison_curves.items():
                df = self._to_frame(curve)
                if df.empty:
                    continue
                ax.plot(df["timestamp"], df["equity"], label=name, linestyle="--", alpha=0.7)
        ax.set_title("Equity Curve")
        ax.legend()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))

        # Drawdown
        ax = axes[0, 1]
        dd = self._drawdown_series(primary_df)
        if not dd.empty:
            ax.fill_between(primary_df["timestamp"], dd * 100, step="mid", alpha=0.4, label=strategy_name)
        if comparison_curves:
            for name, curve in comparison_curves.items():
                df = self._to_frame(curve)
                dd2 = self._drawdown_series(df)
                if dd2.empty:
                    continue
                ax.plot(df["timestamp"], dd2 * 100, label=f"{name} dd", linestyle="--", alpha=0.6)
        ax.set_title("Drawdown (%)")
        ax.legend()

        # Histogram
        ax = axes[1, 0]
        df_trades = self._trades_frame(trades)
        if not df_trades.empty:
            ax.hist(df_trades["pnl"], bins=30, alpha=0.6, label=strategy_name, color="#4c72b0")
        ax.set_title("Trade P&L Distribution")
        ax.set_xlabel("P&L")
        ax.set_ylabel("Frequency")

        # Calendar
        ax = axes[1, 1]
        if df_trades.empty:
            ax.text(0.5, 0.5, "No trades", ha="center", va="center")
            ax.axis("off")
        else:
            df_trades["date"] = df_trades["exit_time"].dt.date
            daily = df_trades.groupby("date")["pnl"].sum().reset_index()
            daily["date"] = pd.to_datetime(daily["date"])
            daily["week"] = daily["date"].dt.isocalendar().week
            daily["dow"] = daily["date"].dt.dayofweek
            pivot = daily.pivot(index="dow", columns="week", values="pnl").sort_index(ascending=False)
            c = ax.imshow(pivot, aspect="auto", cmap="RdYlGn", interpolation="nearest")
            ax.set_yticks(range(7))
            ax.set_yticklabels(["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][::-1])
            ax.set_xticks(range(len(pivot.columns)))
            ax.set_xticklabels(pivot.columns)
            ax.set_xlabel("ISO Week")
            ax.set_title("Win/Loss Calendar")
            fig.colorbar(c, ax=ax, label="Daily P&L")

        fig.suptitle(f"Backtest: {strategy_name}", fontsize=14)
        fig.autofmt_xdate(rotation=15)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        out = self.output_dir / f"{strategy_name}_dashboard.png"
        fig.savefig(out, dpi=170)
        plt.close(fig)
        return out

