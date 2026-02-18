"""Web dashboard for Stonkers trading bot (PWA-enabled)."""
import os
import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from flask import Flask, jsonify, request, send_from_directory

# Dashboard will be initialized with these references
_db = None
_trader = None
_strategies = None
_config = None
_alpaca = None

# Resolve static directory relative to this file's location
_static_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')

app = Flask(__name__, static_folder=_static_dir, static_url_path='/static')


@app.route("/")
def index():
    """Serve the PWA dashboard."""
    return send_from_directory(_static_dir, 'index.html')


def _safe_float(value, default=None):
    """Safely convert a value to float, returning default if None or invalid."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _symbol_to_pair(symbol: str) -> str:
    """Convert Alpaca symbol format to pair format (e.g. 'ETHUSD' -> 'ETH/USD')."""
    if '/' in symbol:
        return symbol
    # Handle common quote currencies
    for suffix in ('USD', 'USDT', 'BTC', 'EUR'):
        if symbol.endswith(suffix) and len(symbol) > len(suffix):
            return symbol[:-len(suffix)] + '/' + suffix
    return symbol


def _get_positions_live():
    """Fetch positions from Alpaca API and enrich with local DB data."""
    positions = []
    if not _alpaca:
        return positions

    try:
        alpaca_positions = _alpaca.get_open_positions()
    except Exception:
        alpaca_positions = []

    # Build lookup of local DB positions by pair for enrichment
    db_positions_by_pair = {}
    if _db:
        try:
            for pos in _db.get_open_positions():
                db_positions_by_pair[pos.pair] = pos
        except Exception:
            pass

    for ap in alpaca_positions:
        # Alpaca position attributes are strings (even numeric ones)
        # and Optional fields can be None
        symbol = getattr(ap, 'symbol', '') or ''
        pair = _symbol_to_pair(symbol)

        qty = abs(_safe_float(getattr(ap, 'qty', None), 0))
        # side is a PositionSide(str, Enum) - use .value for clean serialization
        side_raw = getattr(ap, 'side', 'long')
        side = side_raw.value if hasattr(side_raw, 'value') else str(side_raw)
        entry_price = _safe_float(getattr(ap, 'avg_entry_price', None), 0)
        current_price = _safe_float(getattr(ap, 'current_price', None))
        market_value = _safe_float(getattr(ap, 'market_value', None))
        unrealized_pl = _safe_float(getattr(ap, 'unrealized_pl', None))
        unrealized_plpc_raw = _safe_float(getattr(ap, 'unrealized_plpc', None))
        unrealized_plpc = round(unrealized_plpc_raw * 100, 2) if unrealized_plpc_raw is not None else None
        cost_basis = _safe_float(getattr(ap, 'cost_basis', None), 0)

        # Enrich with local DB data if available
        db_pos = db_positions_by_pair.get(pair)
        strategy = db_pos.strategy_name if db_pos else 'external'
        entry_time = db_pos.entry_time.strftime('%Y-%m-%d %H:%M') if db_pos else ''
        stop_loss = float(db_pos.stop_loss_price) if db_pos and db_pos.stop_loss_price else None
        take_profit = float(db_pos.take_profit_price) if db_pos and db_pos.take_profit_price else None

        positions.append({
            'pair': pair,
            'symbol': symbol,
            'direction': side,
            'entry_price': entry_price,
            'current_price': current_price,
            'quantity': qty,
            'market_value': market_value,
            'cost_basis': cost_basis,
            'unrealized_pnl': unrealized_pl,
            'unrealized_pnl_pct': unrealized_plpc,
            'strategy': strategy,
            'entry_time': entry_time,
            'stop_loss': stop_loss,
            'take_profit': take_profit,
            'source': 'alpaca',
        })

    return positions


def _get_positions_paper():
    """Fetch positions from local DB (paper trading mode)."""
    positions = []
    if not _db:
        return positions

    try:
        open_positions = _db.get_open_positions()
        for pos in open_positions:
            positions.append({
                'pair': pos.pair,
                'symbol': pos.pair.replace('/', ''),
                'direction': pos.direction.value,
                'entry_price': float(pos.entry_price),
                'current_price': None,
                'quantity': float(pos.quantity),
                'market_value': None,
                'cost_basis': float(pos.entry_price * pos.quantity),
                'unrealized_pnl': None,
                'unrealized_pnl_pct': None,
                'strategy': pos.strategy_name,
                'entry_time': pos.entry_time.strftime('%Y-%m-%d %H:%M'),
                'stop_loss': float(pos.stop_loss_price) if pos.stop_loss_price else None,
                'take_profit': float(pos.take_profit_price) if pos.take_profit_price else None,
                'source': 'paper',
            })
    except Exception:
        pass

    return positions


def _compute_pnl_metrics():
    """Compute P&L metrics for the last 7 days."""
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

    return {
        'total': pnl_total,
        'win_rate': pnl_win_rate,
        'trade_count': pnl_trade_count,
        'profit_factor': pnl_profit_factor,
    }


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

    # Get open positions from appropriate source
    if not paper_mode and _alpaca:
        positions = _get_positions_live()
    else:
        positions = _get_positions_paper()

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

    # Get recent signal activity
    signals = []
    if _db:
        try:
            signals = _db.get_recent_signal_logs(limit=20)
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
    pnl_metrics = _compute_pnl_metrics()

    return jsonify({
        'cash': float(cash),
        'equity': float(equity),
        'paper_mode': paper_mode,
        'positions': positions,
        'trades': trades,
        'signals': signals,
        'strategies': strategy_list,
        'pnl': pnl_metrics,
        'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC'),
    })


@app.route("/api/positions/close", methods=["POST"])
def api_close_position():
    """Emergency close a position via Alpaca API."""
    if not _alpaca:
        return jsonify({'error': 'No exchange connector available'}), 503

    data = request.get_json()
    if not data or 'symbol' not in data:
        return jsonify({'error': 'Missing symbol parameter'}), 400

    symbol = data['symbol']

    try:
        success = _alpaca.close_position(symbol)
        if success:
            # Also close in local DB if tracked
            if _db:
                try:
                    pair = _symbol_to_pair(symbol)
                    open_positions = _db.get_open_positions()
                    for pos in open_positions:
                        if pos.pair == pair:
                            from src.engine.position_manager import PositionManager
                            pm = PositionManager(_db)
                            pm.close_position(pair, pos.entry_price, 'manual_emergency_close')
                            break
                except Exception:
                    pass  # DB cleanup is best-effort

            return jsonify({'success': True, 'message': f'Position {symbol} closed'})
        else:
            return jsonify({'error': f'Failed to close position {symbol}'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


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


def init_dashboard(db, trader, strategies, config, alpaca=None):
    """Initialize dashboard with references to bot components."""
    global _db, _trader, _strategies, _config, _alpaca
    _db = db
    _trader = trader
    _strategies = strategies
    _config = config
    _alpaca = alpaca


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
