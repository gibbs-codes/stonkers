"""Configuration loader for the trading bot."""
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import List

import yaml
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ExchangeConfig:
    """Exchange connection settings."""
    name: str
    paper: bool
    api_key: str
    secret_key: str


@dataclass
class TradingConfig:
    """Trading pair and timeframe settings."""
    pairs: List[str]
    default_timeframe: str


@dataclass
class PaperTradingConfig:
    """Paper trading settings."""
    enabled: bool
    starting_balance: Decimal
    slippage_pct: Decimal  # Simulated slippage percentage


@dataclass
class RiskConfig:
    """Risk management settings."""
    max_position_pct: Decimal
    max_daily_loss_pct: Decimal
    max_open_positions: int
    stop_loss_pct: Decimal
    take_profit_pct: Decimal


@dataclass
class LoggingConfig:
    """Logging settings."""
    level: str
    log_signals: bool
    log_decisions: bool
    log_to_file: bool


@dataclass
class Config:
    """Main configuration container."""
    exchange: ExchangeConfig
    trading: TradingConfig
    paper_trading: PaperTradingConfig
    risk: RiskConfig
    logging: LoggingConfig

    @classmethod
    def from_yaml(cls, config_path: Path = Path("config.yaml")) -> "Config":
        """Load configuration from YAML file.

        Args:
            config_path: Path to config YAML file

        Returns:
            Config instance
        """
        # Load YAML
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        with open(config_path) as f:
            data = yaml.safe_load(f)

        # Parse exchange config
        exchange_data = data.get("exchange", {})
        exchange = ExchangeConfig(
            name=exchange_data.get("name", "alpaca"),
            paper=exchange_data.get("paper", True),
            api_key=os.getenv("ALPACA_API_KEY", ""),
            secret_key=os.getenv("ALPACA_SECRET_KEY", ""),
        )

        # Parse trading config
        trading_data = data.get("trading", {})
        trading = TradingConfig(
            pairs=trading_data.get("pairs", ["BTC/USD"]),
            default_timeframe=trading_data.get("default_timeframe", "15m"),
        )

        # Parse paper trading config
        paper_data = data.get("paper_trading", {})
        paper_trading = PaperTradingConfig(
            enabled=paper_data.get("enabled", True),
            starting_balance=Decimal(str(paper_data.get("starting_balance", 10000))),
            slippage_pct=Decimal(str(paper_data.get("slippage_pct", 0.001))),  # 0.1% default
        )

        # Parse risk config
        risk_data = data.get("risk", {})
        risk = RiskConfig(
            max_position_pct=Decimal(str(risk_data.get("max_position_pct", 0.2))),
            max_daily_loss_pct=Decimal(str(risk_data.get("max_daily_loss_pct", 0.05))),
            max_open_positions=risk_data.get("max_open_positions", 5),
            stop_loss_pct=Decimal(str(risk_data.get("stop_loss_pct", 0.02))),
            take_profit_pct=Decimal(str(risk_data.get("take_profit_pct", 0.05))),
        )

        # Parse logging config
        logging_data = data.get("logging", {})
        logging_config = LoggingConfig(
            level=logging_data.get("level", "INFO"),
            log_signals=logging_data.get("log_signals", True),
            log_decisions=logging_data.get("log_decisions", True),
            log_to_file=logging_data.get("log_to_file", True),
        )

        return cls(
            exchange=exchange,
            trading=trading,
            paper_trading=paper_trading,
            risk=risk,
            logging=logging_config,
        )
