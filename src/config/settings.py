"""Configuration management system."""
import os
from pathlib import Path
from typing import Any, Dict
import yaml
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class Config:
    """Global configuration manager."""

    def __init__(self, config_path: str = None):
        """
        Load configuration from YAML file.

        Args:
            config_path: Path to config file. If None, uses default_config.yaml
        """
        if config_path is None:
            config_dir = Path(__file__).parent
            config_path = config_dir / "default_config.yaml"

        with open(config_path, 'r') as f:
            self._config = yaml.safe_load(f)

        # Load sensitive data from environment
        self._load_secrets()

    def _load_secrets(self):
        """Load API keys and secrets from environment variables."""
        exchange_name = self._config['exchange']['name'].lower()

        # Exchange-specific environment variable mapping
        if exchange_name == 'alpaca':
            api_key = os.getenv('ALPACA_API_KEY')
            api_secret = os.getenv('ALPACA_SECRET_KEY')
        elif exchange_name == 'binance':
            # Legacy Binance support
            testnet = self._config['exchange'].get('testnet', True)
            if testnet:
                api_key = os.getenv('BINANCE_TESTNET_API_KEY')
                api_secret = os.getenv('BINANCE_TESTNET_SECRET')
            else:
                api_key = os.getenv('BINANCE_API_KEY')
                api_secret = os.getenv('BINANCE_SECRET')
        else:
            # Generic fallback - exchange name in uppercase
            prefix = exchange_name.upper()
            api_key = os.getenv(f'{prefix}_API_KEY')
            api_secret = os.getenv(f'{prefix}_SECRET_KEY')

        self._config['exchange']['api_key'] = api_key
        self._config['exchange']['api_secret'] = api_secret

    def get(self, key_path: str, default=None) -> Any:
        """
        Get config value using dot notation.

        Example:
            config.get('exchange.name') -> 'binance'
            config.get('risk.max_position_pct') -> 0.1
        """
        keys = key_path.split('.')
        value = self._config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def get_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        """Get configuration for a specific strategy."""
        strategies = self._config.get('strategies', {})
        return strategies.get(strategy_name, {})

    def is_strategy_enabled(self, strategy_name: str) -> bool:
        """Check if a strategy is enabled."""
        strategy_config = self.get_strategy_config(strategy_name)
        return strategy_config.get('enabled', False)

    def get_enabled_strategies(self) -> Dict[str, Dict[str, Any]]:
        """Get all enabled strategies and their configs."""
        strategies = self._config.get('strategies', {})
        return {
            name: config
            for name, config in strategies.items()
            if config.get('enabled', False)
        }

    @property
    def exchange_name(self) -> str:
        return self.get('exchange.name')

    @property
    def is_testnet(self) -> bool:
        """For backward compatibility - maps to paper_trading for most exchanges."""
        return self.get('exchange.testnet') or self.get('exchange.paper_trading', True)

    @property
    def is_paper_trading(self) -> bool:
        return self.get('paper_trading.enabled', True)

    @property
    def trading_pairs(self) -> list:
        return self.get('trading.pairs', [])

    @property
    def default_timeframe(self) -> str:
        return self.get('trading.default_timeframe', '15m')


# Global config instance
config = Config()
