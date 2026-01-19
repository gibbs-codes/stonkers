"""Strategy registry for managing enabled strategies."""
from typing import Dict, List
from src.strategies.base import Strategy
from src.strategies.ema_rsi import EmaRsiStrategy
from src.strategies.ema_crossover import EmaCrossoverStrategy
from src.strategies.bollinger_squeeze import BollingerSqueezeStrategy
from src.strategies.rsi_divergence import RsiDivergenceStrategy
from src.config.settings import config


class StrategyRegistry:
    """Registry for managing and executing strategies."""

    # Available strategy classes
    _available_strategies = {
        'ema_rsi': EmaRsiStrategy,
        'ema_crossover': EmaCrossoverStrategy,
        'bollinger_squeeze': BollingerSqueezeStrategy,
        'rsi_divergence': RsiDivergenceStrategy
    }

    def __init__(self):
        """Initialize strategy registry."""
        self.strategies: Dict[str, Strategy] = {}
        self._load_enabled_strategies()

    def _load_enabled_strategies(self):
        """Load and configure enabled strategies from config."""
        enabled_strategies = config.get_enabled_strategies()

        for strategy_name, strategy_config in enabled_strategies.items():
            if strategy_name in self._available_strategies:
                # Instantiate strategy
                strategy_class = self._available_strategies[strategy_name]
                strategy = strategy_class()

                # Configure with parameters
                params = strategy_config.get('params', {})
                strategy.configure(params)

                # Add to registry
                self.strategies[strategy_name] = strategy

    def get_strategy(self, name: str) -> Strategy:
        """
        Get strategy by name.

        Args:
            name: Strategy name

        Returns:
            Strategy instance

        Raises:
            KeyError if strategy not found or not enabled
        """
        if name not in self.strategies:
            raise KeyError(f"Strategy '{name}' not found or not enabled")
        return self.strategies[name]

    def get_all_strategies(self) -> List[Strategy]:
        """Get all enabled strategies."""
        return list(self.strategies.values())

    def is_enabled(self, name: str) -> bool:
        """Check if strategy is enabled."""
        return name in self.strategies

    @property
    def enabled_count(self) -> int:
        """Number of enabled strategies."""
        return len(self.strategies)

    def __repr__(self) -> str:
        """String representation."""
        strategy_names = list(self.strategies.keys())
        return f"StrategyRegistry(enabled={strategy_names})"
