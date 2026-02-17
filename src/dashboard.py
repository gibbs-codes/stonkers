"""Simple web dashboard for Stonkers trading bot."""
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from flask import Flask, render_template_string

# Dashboard will be initialized with these references
_db = None
_trader = None
_strategies = None
_config = None

app = Flask(__name__)

# Simple HTML template - all in one file, no external dependencies
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>Stonkers Dashboard</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta http-equiv="refresh" content="60">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #1a1a2e;
            color: #eee;
            padding: 20px;
            max-width: 800px;
            margin: 0 auto;
        }
        h1 { color: #00d4ff; margin-bottom: 20px; }
        h2 { color: #888; font-size: 14px; text-transform: uppercase; margin: 20px 0 10px; }
        .card {
            background: #16213e;
            border-radius: 8px;
            padding: 15px;
            margin-bottom: 15px;
        }
        .stat { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #333; }
        .stat:last-child { border-bottom: none; }
        .stat-label { color: #888; }
        .stat-value { font-weight: bold; }
        .positive { color: #00ff88; }
        .negative { color: #ff4757; }
        .neutral { color: #ffa502; }
        .position {
            background: #1e3a5f;
            border-radius: 6px;
            padding: 12px;
            margin-bottom: 10px;
        }
        .position-header { display: flex; justify-content: space-between; margin-bottom: 8px; }
        .position-pair { font-weight: bold; font-size: 16px; }
        .long { color: #00ff88; }
        .short { color: #ff4757; }
        .strategy-list { display: flex; flex-wrap: wrap; gap: 8px; }
        .strategy-tag {
            background: #2d4a6f;
            padding: 5px 10px;
            border-radius: 4px;
            font-size: 12px;
        }
        .strategy-tag.enabled { background: #1e5128; }
        .strategy-tag.disabled { background: #4a1e1e; opacity: 0.6; }
        .timestamp { color: #666; font-size: 12px; text-align: center; margin-top: 20px; }
        .no-data { color: #666; font-style: italic; }
    </style>
</head>
<body>
    <h1>Stonkers Dashboard</h1>

    <h2>Account</h2>
    <div class="card">
        <div class="stat">
            <span class="stat-label">Cash Balance</span>
            <span class="stat-value">${{ "%.2f"|format(cash) }}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Total Equity</span>
            <span class="stat-value">${{ "%.2f"|format(equity) }}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Mode</span>
            <span class="stat-value {{ 'neutral' if paper_mode else 'negative' }}">
                {{ 'Paper Trading' if paper_mode else 'LIVE TRADING' }}
            </span>
        </div>
    </div>

    <h2>P&amp;L (7 days)</h2>
    <div class="card">
        <div class="stat">
            <span class="stat-label">Total P&amp;L</span>
            <span class="stat-value {{ 'positive' if pnl_total >= 0 else 'negative' }}">
                ${{ "%.2f"|format(pnl_total) }}
            </span>
        </div>
        <div class="stat">
            <span class="stat-label">Win Rate</span>
            <span class="stat-value">{{ "%.1f"|format(pnl_win_rate) }}%</span>
        </div>
        <div class="stat">
            <span class="stat-label">Total Trades</span>
            <span class="stat-value">{{ pnl_trade_count }}</span>
        </div>
        <div class="stat">
            <span class="stat-label">Profit Factor</span>
            <span class="stat-value">{{ "%.2f"|format(pnl_profit_factor) }}</span>
        </div>
    </div>

    <h2>Open Positions ({{ positions|length }})</h2>
    <div class="card">
        {% if positions %}
            {% for pos in positions %}
            <div class="position">
                <div class="position-header">
                    <span class="position-pair">{{ pos.pair }}</span>
                    <span class="{{ 'long' if pos.direction == 'long' else 'short' }}">
                        {{ pos.direction|upper }}
                    </span>
                </div>
                <div class="stat">
                    <span class="stat-label">Entry Price</span>
                    <span class="stat-value">${{ "%.2f"|format(pos.entry_price) }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Quantity</span>
                    <span class="stat-value">{{ "%.4f"|format(pos.quantity) }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Strategy</span>
                    <span class="stat-value">{{ pos.strategy }}</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Opened</span>
                    <span class="stat-value">{{ pos.entry_time }}</span>
                </div>
            </div>
            {% endfor %}
        {% else %}
            <p class="no-data">No open positions</p>
        {% endif %}
    </div>

    <h2>Recent Trades ({{ trades|length }})</h2>
    <div class="card">
        {% if trades %}
            {% for trade in trades %}
            <div class="stat">
                <span class="stat-label">
                    {{ trade.pair }} {{ trade.direction|upper }}
                </span>
                <span class="stat-value {{ 'positive' if trade.pnl >= 0 else 'negative' }}">
                    ${{ "%.2f"|format(trade.pnl) }} ({{ "%.1f"|format(trade.pnl_pct) }}%)
                </span>
            </div>
            {% endfor %}
        {% else %}
            <p class="no-data">No recent trades</p>
        {% endif %}
    </div>

    <h2>Strategies</h2>
    <div class="card">
        <div class="strategy-list">
            {% for strat in strategies %}
            <span class="strategy-tag {{ 'enabled' if strat.enabled else 'disabled' }}">
                {{ strat.name }}
            </span>
            {% endfor %}
        </div>
    </div>

    <p class="timestamp">Last updated: {{ timestamp }} (auto-refreshes every 60s)</p>
</body>
</html>
"""


@app.route("/")
def dashboard():
    """Render the dashboard."""
    # Get account info
    cash = Decimal("0")
    equity = Decimal("0")
    paper_mode = True

    if _trader:
        try:
            cash = _trader.get_cash_balance()
            equity = _trader.get_account_value()
        except Exception:
            pass

    if _config:
        paper_mode = getattr(_config.paper_trading, 'enabled', True)

    # Get open positions
    positions = []
    if _db:
        try:
            open_positions = _db.get_open_positions()
            for pos in open_positions:
                positions.append({
                    'pair': pos.pair,
                    'direction': pos.direction.value,
                    'entry_price': float(pos.entry_price),
                    'quantity': float(pos.quantity),
                    'strategy': pos.strategy_name,
                    'entry_time': pos.entry_time.strftime('%Y-%m-%d %H:%M'),
                })
        except Exception:
            pass

    # Get recent trades
    trades = []
    if _db:
        try:
            recent_trades = _db.get_recent_trades(limit=10)
            for trade in recent_trades:
                trades.append({
                    'pair': trade['pair'],
                    'direction': trade['direction'],
                    'pnl': float(trade['pnl']),
                    'pnl_pct': float(trade['pnl_pct']),
                })
        except Exception:
            pass

    # Get strategies
    strategy_list = []
    if _strategies:
        for strat in _strategies:
            strategy_list.append({
                'name': strat.name,
                'enabled': True,
            })

    # Compute P&L metrics (last 7 days)
    pnl_total = 0.0
    pnl_win_rate = 0.0
    pnl_trade_count = 0
    pnl_profit_factor = 0.0
    if _db:
        try:
            since = datetime.now(timezone.utc) - timedelta(days=7)
            pnl_trades = _db.get_trades_by_strategy(since=since)
            if pnl_trades:
                pnl_trade_count = len(pnl_trades)
                pnl_total = float(sum(t["pnl"] for t in pnl_trades))
                winners = [t for t in pnl_trades if t["pnl"] > 0]
                losers = [t for t in pnl_trades if t["pnl"] <= 0]
                pnl_win_rate = (len(winners) / pnl_trade_count) * 100
                gross_profit = float(sum(t["pnl"] for t in winners))
                gross_loss = abs(float(sum(t["pnl"] for t in losers)))
                pnl_profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        except Exception:
            pass

    return render_template_string(
        DASHBOARD_HTML,
        cash=float(cash),
        equity=float(equity),
        paper_mode=paper_mode,
        positions=positions,
        trades=trades,
        strategies=strategy_list,
        pnl_total=pnl_total,
        pnl_win_rate=pnl_win_rate,
        pnl_trade_count=pnl_trade_count,
        pnl_profit_factor=pnl_profit_factor,
        timestamp=datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    )


@app.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.route("/api/status")
def api_status():
    """JSON API endpoint for status."""
    cash = Decimal("0")
    equity = Decimal("0")

    if _trader:
        try:
            cash = _trader.get_cash_balance()
            equity = _trader.get_account_value()
        except Exception:
            pass

    positions = []
    if _db:
        try:
            for pos in _db.get_open_positions():
                positions.append({
                    'pair': pos.pair,
                    'direction': pos.direction.value,
                    'entry_price': str(pos.entry_price),
                    'quantity': str(pos.quantity),
                })
        except Exception:
            pass

    return {
        "cash": str(cash),
        "equity": str(equity),
        "open_positions": len(positions),
        "positions": positions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


def init_dashboard(db, trader, strategies, config):
    """Initialize dashboard with references to bot components."""
    global _db, _trader, _strategies, _config
    _db = db
    _trader = trader
    _strategies = strategies
    _config = config


def start_dashboard(port: int = 3004):
    """Start dashboard in a background thread."""
    def run():
        # Suppress Flask's default logging
        import logging
        log = logging.getLogger('werkzeug')
        log.setLevel(logging.WARNING)

        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
