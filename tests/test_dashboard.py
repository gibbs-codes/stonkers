"""Tests for dashboard API and helper functions."""
import json
import tempfile
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.data.database import Database
from src.engine.paper_trader import PaperTrader
from src.models.position import Direction, Position, PositionStatus
from src.models.signal import Signal, SignalType


# --- Fixtures ---


@pytest.fixture
def db():
    """Create temporary database."""
    with tempfile.NamedTemporaryFile(suffix=".db") as f:
        yield Database(Path(f.name))


@pytest.fixture
def paper_trader(db):
    """Create paper trader with $10,000 starting balance."""
    return PaperTrader(db, initial_balance=Decimal("10000"))


@pytest.fixture
def mock_config():
    """Create mock config object."""
    config = MagicMock()
    config.paper_trading.enabled = True
    return config


@pytest.fixture
def mock_config_live():
    """Create mock config for live trading mode."""
    config = MagicMock()
    config.paper_trading.enabled = False
    return config


@pytest.fixture
def strategies():
    """Create mock strategy list."""
    strat1 = MagicMock()
    strat1.name = "EMA_RSI"
    strat2 = MagicMock()
    strat2.name = "RSI_DIVERGENCE"
    return [strat1, strat2]


class FakePositionSide(str, Enum):
    """Mimics alpaca.trading.enums.PositionSide."""
    LONG = "long"
    SHORT = "short"


def make_alpaca_position(**overrides):
    """Create a mock Alpaca position object with string-typed fields."""
    defaults = {
        'symbol': 'ETHUSD',
        'qty': '0.5',
        'side': FakePositionSide.LONG,
        'avg_entry_price': '2500.00',
        'current_price': '2600.00',
        'market_value': '1300.00',
        'cost_basis': '1250.00',
        'unrealized_pl': '50.00',
        'unrealized_plpc': '0.04',  # 4%
    }
    defaults.update(overrides)
    pos = MagicMock()
    for k, v in defaults.items():
        setattr(pos, k, v)
    return pos


def make_open_position(pair="ETH/USD", strategy_name="EMA_RSI", **overrides):
    """Create an open Position for DB insertion."""
    defaults = {
        'id': f"pos_{uuid.uuid4().hex[:8]}",
        'pair': pair,
        'direction': Direction.LONG,
        'entry_price': Decimal("2500"),
        'quantity': Decimal("0.5"),
        'entry_time': datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
        'strategy_name': strategy_name,
        'status': PositionStatus.OPEN,
        'stop_loss_price': Decimal("2400"),
        'take_profit_price': Decimal("2700"),
    }
    defaults.update(overrides)
    return Position(**defaults)


# --- Tests for _safe_float ---


class TestSafeFloat:
    def test_converts_string_number(self):
        from src.dashboard import _safe_float
        assert _safe_float("123.45") == 123.45

    def test_converts_int(self):
        from src.dashboard import _safe_float
        assert _safe_float(42) == 42.0

    def test_returns_default_for_none(self):
        from src.dashboard import _safe_float
        assert _safe_float(None) is None
        assert _safe_float(None, 0) == 0

    def test_returns_default_for_invalid_string(self):
        from src.dashboard import _safe_float
        assert _safe_float("not_a_number", 0) == 0

    def test_returns_default_for_empty_string(self):
        from src.dashboard import _safe_float
        assert _safe_float("", 0) == 0

    def test_handles_negative(self):
        from src.dashboard import _safe_float
        assert _safe_float("-5.5") == -5.5


# --- Tests for _symbol_to_pair ---


class TestSymbolToPair:
    def test_converts_usd_pair(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("ETHUSD") == "ETH/USD"

    def test_converts_btc_usd(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("BTCUSD") == "BTC/USD"

    def test_converts_sol_usd(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("SOLUSD") == "SOL/USD"

    def test_converts_doge_usd(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("DOGEUSD") == "DOGE/USD"

    def test_preserves_already_formatted(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("ETH/USD") == "ETH/USD"

    def test_handles_usdt_quote(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("BTCUSDT") == "BTC/USDT"

    def test_handles_unknown_format(self):
        from src.dashboard import _symbol_to_pair
        # No recognized suffix - returns as-is
        assert _symbol_to_pair("ABCXYZ") == "ABCXYZ"

    def test_handles_empty_string(self):
        from src.dashboard import _symbol_to_pair
        assert _symbol_to_pair("") == ""

    def test_wont_split_just_suffix(self):
        from src.dashboard import _symbol_to_pair
        # "USD" alone should not become "/USD"
        assert _symbol_to_pair("USD") == "USD"


# --- Tests for _get_positions_live ---


class TestGetPositionsLive:
    def setup_method(self):
        """Reset dashboard module globals before each test."""
        import src.dashboard as dash
        self.dash = dash
        dash._alpaca = None
        dash._db = None
        dash._trader = None
        dash._strategies = None
        dash._config = None

    def test_returns_empty_when_no_alpaca(self):
        self.dash._alpaca = None
        assert self.dash._get_positions_live() == []

    def test_returns_empty_when_alpaca_raises(self):
        alpaca = MagicMock()
        alpaca.get_open_positions.side_effect = Exception("API error")
        self.dash._alpaca = alpaca
        assert self.dash._get_positions_live() == []

    def test_parses_alpaca_position_with_all_fields(self):
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [make_alpaca_position()]
        self.dash._alpaca = alpaca

        result = self.dash._get_positions_live()
        assert len(result) == 1
        pos = result[0]
        assert pos['pair'] == 'ETH/USD'
        assert pos['symbol'] == 'ETHUSD'
        assert pos['direction'] == 'long'
        assert pos['entry_price'] == 2500.0
        assert pos['current_price'] == 2600.0
        assert pos['quantity'] == 0.5
        assert pos['market_value'] == 1300.0
        assert pos['unrealized_pnl'] == 50.0
        assert pos['unrealized_pnl_pct'] == 4.0  # 0.04 * 100
        assert pos['cost_basis'] == 1250.0
        assert pos['strategy'] == 'external'  # No DB match
        assert pos['source'] == 'alpaca'

    def test_handles_none_optional_fields(self):
        """Alpaca Optional[str] fields can be None - must not crash."""
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [
            make_alpaca_position(
                current_price=None,
                market_value=None,
                unrealized_pl=None,
                unrealized_plpc=None,
            )
        ]
        self.dash._alpaca = alpaca

        result = self.dash._get_positions_live()
        assert len(result) == 1
        pos = result[0]
        assert pos['current_price'] is None
        assert pos['market_value'] is None
        assert pos['unrealized_pnl'] is None
        assert pos['unrealized_pnl_pct'] is None
        # Non-optional fields still work
        assert pos['entry_price'] == 2500.0
        assert pos['quantity'] == 0.5

    def test_enriches_with_db_data(self, db):
        """When position exists in local DB, strategy/SL/TP should be populated."""
        # Insert position in DB
        db_pos = make_open_position()
        db.insert_position(db_pos)

        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [make_alpaca_position()]
        self.dash._alpaca = alpaca
        self.dash._db = db

        result = self.dash._get_positions_live()
        assert len(result) == 1
        pos = result[0]
        assert pos['strategy'] == 'EMA_RSI'
        assert pos['stop_loss'] == 2400.0
        assert pos['take_profit'] == 2700.0
        assert pos['entry_time'] == '2026-02-12 10:00'

    def test_external_position_no_db_match(self, db):
        """Position on Alpaca but not in DB should show as 'external'."""
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [
            make_alpaca_position(symbol='SOLUSD')
        ]
        self.dash._alpaca = alpaca
        self.dash._db = db  # DB has no SOL position

        result = self.dash._get_positions_live()
        assert len(result) == 1
        assert result[0]['strategy'] == 'external'
        assert result[0]['stop_loss'] is None
        assert result[0]['take_profit'] is None
        assert result[0]['entry_time'] == ''

    def test_short_position_direction(self):
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [
            make_alpaca_position(side=FakePositionSide.SHORT, qty='-0.5')
        ]
        self.dash._alpaca = alpaca

        result = self.dash._get_positions_live()
        assert result[0]['direction'] == 'short'
        assert result[0]['quantity'] == 0.5  # abs()

    def test_multiple_positions(self):
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [
            make_alpaca_position(symbol='ETHUSD'),
            make_alpaca_position(symbol='SOLUSD', avg_entry_price='150.00'),
        ]
        self.dash._alpaca = alpaca

        result = self.dash._get_positions_live()
        assert len(result) == 2
        assert result[0]['pair'] == 'ETH/USD'
        assert result[1]['pair'] == 'SOL/USD'


# --- Tests for _get_positions_paper ---


class TestGetPositionsPaper:
    def setup_method(self):
        import src.dashboard as dash
        self.dash = dash
        dash._alpaca = None
        dash._db = None
        dash._trader = None
        dash._strategies = None
        dash._config = None

    def test_returns_empty_when_no_db(self):
        self.dash._db = None
        assert self.dash._get_positions_paper() == []

    def test_returns_position_from_db(self, db):
        db_pos = make_open_position()
        db.insert_position(db_pos)
        self.dash._db = db

        result = self.dash._get_positions_paper()
        assert len(result) == 1
        pos = result[0]
        assert pos['pair'] == 'ETH/USD'
        assert pos['symbol'] == 'ETHUSD'
        assert pos['direction'] == 'long'
        assert pos['entry_price'] == 2500.0
        assert pos['quantity'] == 0.5
        assert pos['strategy'] == 'EMA_RSI'
        assert pos['source'] == 'paper'
        assert pos['stop_loss'] == 2400.0
        assert pos['take_profit'] == 2700.0
        # Paper mode has no live data
        assert pos['current_price'] is None
        assert pos['unrealized_pnl'] is None
        assert pos['unrealized_pnl_pct'] is None

    def test_position_without_sl_tp(self, db):
        db_pos = make_open_position(stop_loss_price=None, take_profit_price=None)
        db.insert_position(db_pos)
        self.dash._db = db

        result = self.dash._get_positions_paper()
        assert result[0]['stop_loss'] is None
        assert result[0]['take_profit'] is None


# --- Tests for get_recent_signal_logs ---


class TestGetRecentSignalLogs:
    def test_returns_empty_when_no_logs(self, db):
        result = db.get_recent_signal_logs(limit=10)
        assert result == []

    def test_returns_accepted_signal(self, db):
        db.insert_signal_log(
            timestamp=datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
            pair="ETH/USD",
            strategy_name="EMA_RSI",
            signal_type="entry_long",
            strength=0.85,
            status="accepted",
            actual_entry_price=2500.0,
            quantity=0.5,
            position_id="pos_abc123",
        )

        result = db.get_recent_signal_logs(limit=10)
        assert len(result) == 1
        log = result[0]
        assert log['pair'] == 'ETH/USD'
        assert log['strategy'] == 'EMA_RSI'
        assert log['signal_type'] == 'entry_long'
        assert log['strength'] == 0.85
        assert log['status'] == 'accepted'
        assert log['entry_price'] == 2500.0

    def test_returns_rejected_signal(self, db):
        db.insert_signal_log(
            timestamp=datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
            pair="ETH/USD",
            strategy_name="EMA_RSI",
            signal_type="entry_long",
            strength=0.3,
            status="rejected",
            rejection_reason="Signal strength too weak (0.3)",
        )

        result = db.get_recent_signal_logs(limit=10)
        assert len(result) == 1
        assert result[0]['status'] == 'rejected'
        assert result[0]['rejection_reason'] == 'Signal strength too weak (0.3)'

    def test_respects_limit(self, db):
        for i in range(5):
            db.insert_signal_log(
                timestamp=datetime(2026, 2, 12, 10, i, tzinfo=timezone.utc),
                pair="ETH/USD",
                strategy_name="EMA_RSI",
                signal_type="entry_long",
                strength=0.8,
                status="accepted",
            )

        result = db.get_recent_signal_logs(limit=3)
        assert len(result) == 3

    def test_ordered_by_timestamp_desc(self, db):
        db.insert_signal_log(
            timestamp=datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
            pair="ETH/USD",
            strategy_name="OLDER",
            signal_type="entry_long",
            strength=0.8,
            status="accepted",
        )
        db.insert_signal_log(
            timestamp=datetime(2026, 2, 12, 11, 0, tzinfo=timezone.utc),
            pair="SOL/USD",
            strategy_name="NEWER",
            signal_type="entry_short",
            strength=0.9,
            status="accepted",
        )

        result = db.get_recent_signal_logs(limit=10)
        assert result[0]['strategy'] == 'NEWER'
        assert result[1]['strategy'] == 'OLDER'


# --- Tests for /api/dashboard endpoint ---


class TestApiDashboard:
    def setup_method(self):
        import src.dashboard as dash
        self.dash = dash
        self.app = dash.app.test_client()
        dash._alpaca = None
        dash._db = None
        dash._trader = None
        dash._strategies = None
        dash._config = None

    def test_returns_json_with_defaults(self):
        resp = self.app.get('/api/dashboard')
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['cash'] == 0.0
        assert data['equity'] == 0.0
        assert data['paper_mode'] is True
        assert data['positions'] == []
        assert data['trades'] == []
        assert data['signals'] == []
        assert data['strategies'] == []
        assert 'timestamp' in data

    def test_paper_mode_uses_db_positions(self, db, paper_trader, mock_config, strategies):
        db_pos = make_open_position()
        db.insert_position(db_pos)

        self.dash._db = db
        self.dash._trader = paper_trader
        self.dash._config = mock_config
        self.dash._strategies = strategies

        resp = self.app.get('/api/dashboard')
        data = resp.get_json()
        assert data['paper_mode'] is True
        assert len(data['positions']) == 1
        assert data['positions'][0]['source'] == 'paper'
        assert len(data['strategies']) == 2

    def test_live_mode_uses_alpaca_positions(self, db, mock_config_live, strategies):
        alpaca = MagicMock()
        alpaca.get_open_positions.return_value = [make_alpaca_position()]

        trader = MagicMock()
        trader.get_cash_balance.return_value = Decimal("5000")
        trader.get_account_value.return_value = Decimal("5200")

        self.dash._db = db
        self.dash._trader = trader
        self.dash._config = mock_config_live
        self.dash._alpaca = alpaca
        self.dash._strategies = strategies

        resp = self.app.get('/api/dashboard')
        data = resp.get_json()
        assert data['paper_mode'] is False
        assert data['cash'] == 5000.0
        assert data['equity'] == 5200.0
        assert len(data['positions']) == 1
        assert data['positions'][0]['source'] == 'alpaca'
        assert data['positions'][0]['pair'] == 'ETH/USD'

    def test_includes_signal_logs(self, db, mock_config):
        db.insert_signal_log(
            timestamp=datetime(2026, 2, 12, 10, 0, tzinfo=timezone.utc),
            pair="ETH/USD",
            strategy_name="EMA_RSI",
            signal_type="entry_long",
            strength=0.85,
            status="accepted",
        )

        self.dash._db = db
        self.dash._config = mock_config

        resp = self.app.get('/api/dashboard')
        data = resp.get_json()
        assert len(data['signals']) == 1
        assert data['signals'][0]['strategy'] == 'EMA_RSI'


# --- Tests for /api/positions/close endpoint ---


class TestApiClosePosition:
    def setup_method(self):
        import src.dashboard as dash
        self.dash = dash
        self.app = dash.app.test_client()
        dash._alpaca = None
        dash._db = None
        dash._trader = None
        dash._strategies = None
        dash._config = None

    def test_returns_503_when_no_alpaca(self):
        self.dash._alpaca = None
        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({'symbol': 'ETHUSD'}),
            content_type='application/json',
        )
        assert resp.status_code == 503

    def test_returns_400_when_missing_symbol(self):
        self.dash._alpaca = MagicMock()
        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({}),
            content_type='application/json',
        )
        assert resp.status_code == 400

    def test_returns_400_when_no_body(self):
        self.dash._alpaca = MagicMock()
        resp = self.app.post('/api/positions/close', content_type='application/json')
        assert resp.status_code == 400

    def test_successful_close(self):
        alpaca = MagicMock()
        alpaca.close_position.return_value = True
        self.dash._alpaca = alpaca

        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({'symbol': 'ETHUSD'}),
            content_type='application/json',
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data['success'] is True
        alpaca.close_position.assert_called_once_with('ETHUSD')

    def test_failed_close(self):
        alpaca = MagicMock()
        alpaca.close_position.return_value = False
        self.dash._alpaca = alpaca

        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({'symbol': 'ETHUSD'}),
            content_type='application/json',
        )
        assert resp.status_code == 500

    def test_close_also_cleans_up_db(self, db):
        """When a position exists in local DB, closing should clean it up."""
        db_pos = make_open_position()
        db.insert_position(db_pos)

        alpaca = MagicMock()
        alpaca.close_position.return_value = True
        self.dash._alpaca = alpaca
        self.dash._db = db

        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({'symbol': 'ETHUSD'}),
            content_type='application/json',
        )
        assert resp.status_code == 200

        # Verify DB position was closed
        open_positions = db.get_open_positions()
        assert len(open_positions) == 0

    def test_close_handles_exception(self):
        alpaca = MagicMock()
        alpaca.close_position.side_effect = Exception("Network error")
        self.dash._alpaca = alpaca

        resp = self.app.post(
            '/api/positions/close',
            data=json.dumps({'symbol': 'ETHUSD'}),
            content_type='application/json',
        )
        assert resp.status_code == 500
        data = resp.get_json()
        assert 'Network error' in data['error']
