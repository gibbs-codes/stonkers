"""Main trading bot entry point."""
import asyncio
from datetime import datetime
from typing import Dict
from src.config.settings import config
from src.connectors import create_connector
from src.data.fetcher import DataFetcher
from src.data.storage import Database
from src.strategies.registry import StrategyRegistry
from src.engine.paper_trader import PaperTrader
from src.engine.risk_manager import RiskManager
from src.logging.trade_logger import TradeLogger


class TradingBot:
    """Main trading bot orchestrator."""

    def __init__(self):
        """Initialize trading bot."""
        self.logger = TradeLogger()
        self.db = Database()

        # Create connector using factory pattern
        exchange_name = config.get('exchange.name', 'alpaca')
        paper_trading = config.get('exchange.paper_trading', True)
        self.connector = create_connector(exchange_name, paper_trading)

        self.fetcher = DataFetcher(self.connector, self.db)
        self.strategy_registry = StrategyRegistry()
        self.paper_trader = PaperTrader(self.db)
        self.risk_manager = RiskManager(self.db)

        self.running = False
        self.pairs = config.trading_pairs
        self.timeframe = config.default_timeframe

    async def start(self):
        """Start the trading bot."""
        self.logger.log_info("=" * 60)
        self.logger.log_info("🚀 STONKERS - Algorithmic Trading Bot")
        self.logger.log_info("=" * 60)

        # Connect to exchange
        exchange_name = config.get('exchange.name', 'alpaca')
        self.logger.log_info(f"Connecting to {exchange_name.upper()}...")

        paper_trading = config.get('exchange.paper_trading', True)
        if paper_trading:
            self.logger.log_warning("⚠️  PAPER TRADING MODE - Using fake money")
        if config.is_paper_trading:
            self.logger.log_warning("📄 PAPER TRADING ENGINE - No real orders")

        connected = await self.connector.connect()
        if not connected:
            self.logger.log_error(Exception("Connection failed"), "Exchange connection")
            return

        self.logger.log_info("✅ Connected to exchange")

        # Load strategies
        self.logger.log_info(f"\n📊 Loaded {self.strategy_registry.enabled_count} strategies:")
        for strategy in self.strategy_registry.get_all_strategies():
            self.logger.log_info(f"  • {strategy.name}: {strategy.description}")

        # Portfolio status
        self.logger.log_info(f"\n💰 Starting Balance: ${self.paper_trader.balance:.2f}")
        self.logger.log_info(f"📈 Trading Pairs: {', '.join(self.pairs)}")
        self.logger.log_info(f"⏱️  Timeframe: {self.timeframe}")

        # Risk parameters
        risk_metrics = self.risk_manager.get_risk_metrics(
            self.paper_trader.balance,
            self.paper_trader.starting_balance
        )
        self.logger.log_info(f"\n🛡️  Risk Management:")
        self.logger.log_info(f"  • Max position size: {risk_metrics['max_position_pct']:.1f}%")
        self.logger.log_info(f"  • Max open positions: {risk_metrics['max_open_positions']}")
        self.logger.log_info(f"  • Daily loss limit: {risk_metrics['max_daily_loss_pct']:.1f}%")

        self.logger.log_info("\n" + "=" * 60)
        self.logger.log_info("🎯 Starting trading loop...")
        self.logger.log_info("=" * 60 + "\n")

        # Start main loop
        self.running = True
        await self.run()

    async def run(self):
        """Main trading loop."""
        iteration = 0

        while self.running:
            try:
                iteration += 1
                self.logger.log_debug(f"\n--- Iteration {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

                # Fetch latest prices
                current_prices = {}
                for pair in self.pairs:
                    try:
                        price = await self.connector.get_current_price(pair)
                        current_prices[pair] = price
                        self.logger.log_debug(f"{pair}: ${price:.2f}")
                    except Exception as e:
                        self.logger.log_error(e, f"Fetching price for {pair}")

                # Check daily loss limit
                portfolio_value = self.paper_trader.get_portfolio_value(current_prices)
                can_trade, reason = self.risk_manager.check_daily_limit(
                    portfolio_value,
                    self.paper_trader.starting_balance
                )

                if not can_trade:
                    self.logger.log_warning(f"⛔ Trading halted: {reason}")
                    await asyncio.sleep(60)
                    continue

                # Check open positions for exits
                await self._check_position_exits(current_prices)

                # Analyze each pair with each strategy
                for pair in self.pairs:
                    # Fetch latest candles
                    candles = await self.fetcher.fetch_latest_candles(
                        pair=pair,
                        timeframe=self.timeframe,
                        limit=200
                    )

                    if not candles:
                        continue

                    # Run all strategies
                    for strategy in self.strategy_registry.get_all_strategies():
                        signal = strategy.analyze(candles)

                        if signal:
                            self.logger.log_signal(signal)
                            await self._process_signal(signal, current_prices[pair])

                # Log portfolio status every 10 iterations
                if iteration % 10 == 0:
                    self.logger.log_portfolio_status(
                        balance=self.paper_trader.balance,
                        portfolio_value=portfolio_value,
                        open_positions=self.paper_trader.position_count,
                        total_return_pct=self.paper_trader.get_total_return_pct()
                    )

                # Sleep until next iteration (adjust based on timeframe)
                await asyncio.sleep(60)  # Check every minute

            except KeyboardInterrupt:
                self.logger.log_info("\n👋 Shutting down...")
                self.running = False
                break
            except Exception as e:
                self.logger.log_error(e, "Main loop")
                await asyncio.sleep(5)

        # Cleanup
        await self.connector.close()
        self.db.close()
        self.logger.log_info("✅ Shutdown complete")

    async def _process_signal(self, signal, current_price: float):
        """
        Process a trading signal.

        Args:
            signal: Trading signal
            current_price: Current market price
        """
        # Check if we can open a position
        portfolio_value = self.paper_trader.get_portfolio_value({signal.pair: current_price})

        can_open, reason = self.risk_manager.can_open_position(
            signal=signal,
            current_positions=self.paper_trader.position_count,
            account_value=portfolio_value,
            starting_balance=self.paper_trader.starting_balance
        )

        self.logger.log_risk_check(can_open, reason)

        if not can_open:
            self.logger.log_trade_decision(signal, 'REJECTED', reason)
            return

        # Calculate position size
        quantity = self.risk_manager.calculate_position_size(
            signal=signal,
            account_value=portfolio_value,
            current_price=current_price
        )

        # Execute trade
        self.paper_trader.execute_signal(signal, quantity, current_price)
        self.logger.log_trade_decision(
            signal,
            'OPENED',
            f"Risk checks passed, position size: {quantity:.6f}",
            quantity=quantity
        )

    async def _check_position_exits(self, current_prices: Dict[str, float]):
        """
        Check if any open positions should be closed.

        Args:
            current_prices: Dict of pair -> current price
        """
        for position in self.paper_trader.get_open_positions():
            if position.pair not in current_prices:
                continue

            current_price = current_prices[position.pair]

            # Check risk manager for stop loss / take profit
            should_close, reason = self.risk_manager.should_close_position(
                position=position,
                current_price=current_price
            )

            if should_close:
                trade = self.paper_trader.close_position(
                    position.id,
                    current_price,
                    reason
                )
                if trade:
                    self.logger.log_trade_completed(trade)


async def main():
    """Entry point."""
    bot = TradingBot()
    await bot.start()


if __name__ == "__main__":
    asyncio.run(main())
