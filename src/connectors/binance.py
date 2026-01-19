"""Binance exchange connector using ccxt."""
import ccxt.async_support as ccxt
from typing import List, Dict, Any, Optional
from datetime import datetime
import asyncio
from src.connectors.base import ExchangeConnector
from src.data.models import Candle
from src.config.settings import config


class BinanceConnector(ExchangeConnector):
    """Binance exchange connector."""

    def __init__(self):
        """Initialize Binance connector."""
        self.exchange: Optional[ccxt.binance] = None
        self._connected = False

    async def connect(self) -> bool:
        """
        Establish connection to Binance.

        Returns:
            True if connection successful
        """
        try:
            api_key = config.get('exchange.api_key')
            api_secret = config.get('exchange.api_secret')
            testnet = config.is_testnet

            # Initialize exchange
            self.exchange = ccxt.binance({
                'apiKey': api_key,
                'secret': api_secret,
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future' if testnet else 'spot',
                }
            })

            # Set testnet URLs if needed
            if testnet:
                self.exchange.set_sandbox_mode(True)

            # Test connection
            await self.exchange.load_markets()
            self._connected = True

            return True

        except Exception as e:
            print(f"Failed to connect to Binance: {e}")
            self._connected = False
            return False

    async def fetch_ohlcv(
        self,
        pair: str,
        timeframe: str,
        since: datetime = None,
        limit: int = 100
    ) -> List[Candle]:
        """
        Fetch OHLCV candles for a trading pair.

        Args:
            pair: Trading pair (e.g., 'BTC/USDT')
            timeframe: Candle timeframe (e.g., '15m', '1h')
            since: Start time for historical data
            limit: Maximum number of candles to fetch

        Returns:
            List of Candle objects
        """
        if not self._connected:
            raise RuntimeError("Not connected to exchange")

        try:
            # Convert datetime to milliseconds timestamp
            since_ms = None
            if since:
                since_ms = int(since.timestamp() * 1000)

            # Fetch OHLCV data
            ohlcv = await self.exchange.fetch_ohlcv(
                pair,
                timeframe,
                since=since_ms,
                limit=limit
            )

            # Convert to Candle objects
            candles = [
                Candle.from_ccxt(data, pair=pair, timeframe=timeframe)
                for data in ohlcv
            ]

            return candles

        except Exception as e:
            print(f"Error fetching OHLCV for {pair}: {e}")
            return []

    async def get_current_price(self, pair: str) -> float:
        """
        Get current market price for a pair.

        Args:
            pair: Trading pair

        Returns:
            Current price
        """
        if not self._connected:
            raise RuntimeError("Not connected to exchange")

        try:
            ticker = await self.exchange.fetch_ticker(pair)
            return float(ticker['last'])
        except Exception as e:
            print(f"Error fetching price for {pair}: {e}")
            raise

    async def get_balance(self, currency: str = 'USDT') -> float:
        """
        Get account balance for a currency.

        Args:
            currency: Currency symbol

        Returns:
            Available balance
        """
        if not self._connected:
            raise RuntimeError("Not connected to exchange")

        try:
            balance = await self.exchange.fetch_balance()
            return float(balance.get(currency, {}).get('free', 0.0))
        except Exception as e:
            print(f"Error fetching balance: {e}")
            return 0.0

    async def place_order(
        self,
        pair: str,
        side: str,
        order_type: str,
        amount: float,
        price: float = None
    ) -> Dict[str, Any]:
        """
        Place an order on the exchange.

        Args:
            pair: Trading pair
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            amount: Order quantity
            price: Limit price (for limit orders)

        Returns:
            Order details
        """
        if not self._connected:
            raise RuntimeError("Not connected to exchange")

        try:
            if order_type == 'market':
                order = await self.exchange.create_market_order(pair, side, amount)
            elif order_type == 'limit':
                if price is None:
                    raise ValueError("Price required for limit orders")
                order = await self.exchange.create_limit_order(pair, side, amount, price)
            else:
                raise ValueError(f"Unsupported order type: {order_type}")

            return order

        except Exception as e:
            print(f"Error placing order: {e}")
            raise

    async def close(self):
        """Close exchange connection."""
        if self.exchange:
            await self.exchange.close()
            self._connected = False

    @property
    def is_connected(self) -> bool:
        """Check if connected to exchange."""
        return self._connected
