"""Connector factory for creating exchange connectors."""
from src.connectors.base import ExchangeConnector
from src.connectors.alpaca import AlpacaConnector


def create_connector(exchange_name: str, paper_trading: bool = True) -> ExchangeConnector:
    """
    Create an exchange connector based on exchange name.

    Args:
        exchange_name: Name of the exchange ('alpaca', 'binance', etc.)
        paper_trading: Whether to use paper trading mode

    Returns:
        ExchangeConnector instance

    Raises:
        ValueError: If exchange is not supported
    """
    exchange_name = exchange_name.lower()

    if exchange_name == "alpaca":
        return AlpacaConnector(paper_trading=paper_trading)
    elif exchange_name == "binance":
        # Lazy import to avoid requiring ccxt if not using Binance
        from src.connectors.binance import BinanceConnector
        return BinanceConnector()
    else:
        raise ValueError(f"Unsupported exchange: {exchange_name}")


__all__ = ["ExchangeConnector", "AlpacaConnector", "create_connector"]
