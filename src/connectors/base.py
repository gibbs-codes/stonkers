"""Abstract exchange connector interface."""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from datetime import datetime
from src.data.models import Candle


class ExchangeConnector(ABC):
    """Base class for all exchange connectors."""

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to exchange.

        Returns:
            True if connection successful
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def get_current_price(self, pair: str) -> float:
        """
        Get current market price for a pair.

        Args:
            pair: Trading pair

        Returns:
            Current price
        """
        pass

    @abstractmethod
    async def get_balance(self, currency: str = 'USDT') -> float:
        """
        Get account balance for a currency.

        Args:
            currency: Currency symbol

        Returns:
            Available balance
        """
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    async def close(self):
        """Close exchange connection."""
        pass
