"""Web dashboard for Stonkers trading bot (PWA-enabled)."""
import os
import threading
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from flask import Flask, jsonify, send_from_directory

# Dashboard will be initialized with these references
_db = None
_trader = None
_strategies = None
_config = None

# Resolve static directory relative to this file's location
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

app = Flask(__name__, static_folder=_static_dir, static_url_path='/static')


@app.route("/")
def index():
    """Serve the PWA dashboard."""
    return send_from_directory(_static_dir, 'index.html')


@app.route("/api/dashboard")
def api_dashboard():
    """JSON API endpoint for dashboard data (used by the PWA frontend)."""
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

    return jsonify({
        'cash': float(cash),
        'equity': float(equity),
        'paper_mode': paper_mode,
        'positions': positions,
        'trades': trades,
        'strategies': strategy_list,
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    })


@app.route("/health")
def health():
    """Health check endpoint."""
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.route("/api/status")
def api_status():
    """JSON API endpoint for status (legacy)."""
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
