"""Watchdog service for the Stonkers trading bot."""

import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from src.bot.health_monitor import BotHealthMonitor
from src.data.database import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/watchdog.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class BotWatchdog:
    """Watchdog service that monitors and restarts the trading bot."""

    def __init__(self, db_path: str = "data/stonkers.db"):
        """Initialize the watchdog.
        
        Args:
            db_path: Path to the SQLite database
        """
        self.db_path = Path(db_path)
        self.db = None
        self.monitor_script = Path(__file__).parent / "health_monitor.py"
        self.bot_process = None
        self.monitor_process = None
        self.running = False
        
    def connect_database(self) -> bool:
        """Connect to the database.
        
        Returns:
            True if connection successful, False otherwise
        """
        try:
            if self.db_path.exists():
                self.db = Database(self.db_path)
                return True
            else:
                logger.error(f"Database file not found: {self.db_path}")
                return False
        except Exception as e:
            logger.error(f"Failed to connect to database: {e}")
            return False
            
    def disconnect_database(self):
        """Disconnect from the database."""
        if self.db:
            try:
                self.db.close()
            except Exception as e:
                logger.warning(f"Error closing database connection: {e}")
            self.db = None
            
    def is_bot_process_running(self) -> bool:
        """Check if the bot process is running using psutil.
        
        Returns:
            True if process is running, False otherwise
        """
        try:
            # Look for python processes with src.main
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'python' in proc.info['name'] and 'src.main' in ' '.join(proc.info['cmdline']):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            return False
        except Exception as e:
            logger.error(f"Error checking process status: {e}")
            return False
            
    def start_bot_process(self) -> bool:
        """Start the bot process.
        
        Returns:
            True if process started successfully, False otherwise
        """
        try:
            logger.info("Starting bot process...")
            
            # Check if already running
            if self.is_bot_process_running():
                logger.info("Bot process already running")
                return True
                
            # Start the bot in the background
            self.bot_process = subprocess.Popen([
                sys.executable, "-m", "src.main"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            logger.info(f"Started bot process with PID {self.bot_process.pid}")
            return True
        except Exception as e:
            logger.error(f"Error starting bot process: {e}")
            return False
            
    def stop_bot_process(self) -> bool:
        """Stop the bot process.
        
        Returns:
            True if process stopped successfully, False otherwise
        """
        try:
            logger.info("Stopping bot process...")
            
            if not self.is_bot_process_running():
                logger.info("Bot process not running")
                return True
                
            # Find and terminate the process
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'python' in proc.info['name'] and 'src.main' in ' '.join(proc.info['cmdline']):
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)  # Wait up to 10 seconds
                            logger.info(f"Terminated bot process {proc.pid}")
                        except psutil.TimeoutExpired:
                            proc.kill()
                            logger.info(f"Force killed bot process {proc.pid}")
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
                    
            return True
        except Exception as e:
            logger.error(f"Error stopping bot process: {e}")
            return False
            
    def start_monitor_process(self) -> bool:
        """Start the health monitor process.
        
        Returns:
            True if process started successfully, False otherwise
        """
        try:
            logger.info("Starting health monitor process...")
            
            # Check if monitor already running
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if 'python' in proc.info['name'] and 'health_monitor' in ' '.join(proc.info['cmdline']):
                        logger.info("Health monitor already running")
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    pass
            
            # Start monitor in background
            self.monitor_process = subprocess.Popen([
                sys.executable, str(self.monitor_script), "--interval", "30"
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            logger.info(f"Started monitor process with PID {self.monitor_process.pid}")
            return True
        except Exception as e:
            logger.error(f"Error starting monitor process: {e}")
            return False
            
    def check_bot_health(self) -> tuple[bool, str]:
        """Check if the bot is healthy.
        
        Returns:
            Tuple of (is_healthy, reason)
        """
        # Connect to database if needed
        if not self.db:
            if not self.connect_database():
                return False, "Cannot connect to database"
                
        # Check process
        if not self.is_bot_process_running():
            return False, "Bot process not running"
            
        # Check last BOT_START event
        try:
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT timestamp FROM bot_events 
                WHERE event_type = 'BOT_START' 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if not row:
                return False, "No BOT_START event found"
                
            # Check if BOT_START event is recent (within last 2 hours)
            last_start = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            now = datetime.now(last_start.tzinfo)
            if now - last_start > timedelta(hours=2):
                return False, f"Last BOT_START was {now - last_start} ago"
                
            return True, "Bot is healthy"
        except Exception as e:
            logger.error(f"Error checking bot health: {e}")
            return False, f"Error checking health: {e}"
            
    def restart_bot_if_needed(self) -> bool:
        """Restart the bot if it's not healthy.
        
        Returns:
            True if restart successful or not needed, False if restart failed
        """
        is_healthy, reason = self.check_bot_health()
        logger.info(f"Bot health status: {'HEALTHY' if is_healthy else 'UNHEALTHY'} - {reason}")
        
        if is_healthy:
            return True
            
        # Log the issue
        if self.db:
            try:
                self.db.insert_bot_event(
                    event_type="BOT_WATCHDOG_ALERT",
                    message=reason,
                    severity="ERROR"
                )
            except Exception as e:
                logger.error(f"Error logging alert: {e}")
                
        # Restart the bot
        logger.info("Restarting bot...")
        try:
            # Stop the current process
            if not self.stop_bot_process():
                logger.error("Failed to stop bot process")
                return False
                
            # Wait a moment
            time.sleep(5)
            
            # Start a new process
            if not self.start_bot_process():
                logger.error("Failed to start bot process")
                return False
                
            # Log restart
            if self.db:
                try:
                    self.db.insert_bot_event(
                        event_type="BOT_RESTARTED",
                        message="Bot restarted by watchdog",
                        severity="WARNING"
                    )
                except Exception as e:
                    logger.error(f"Error logging restart: {e}")
                    
            logger.info("Bot restarted successfully")
            return True
        except Exception as e:
            logger.error(f"Error restarting bot: {e}")
            return False
            
    def run_once(self):
        """Run a single watchdog cycle."""
        logger.info("Running watchdog cycle...")
        
        # Check and restart bot if needed
        self.restart_bot_if_needed()
        
        # Ensure monitor is running
        self.start_monitor_process()
        
    def run_continuously(self, interval: int = 60):
        """Run the watchdog continuously.
        
        Args:
            interval: Check interval in seconds
        """
        logger.info("Starting watchdog service...")
        self.running = True
        
        # Set up signal handlers
        def signal_handler(signum, frame):
            logger.info(f"Received signal {signum}, shutting down...")
            self.running = False
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        try:
            # Connect to database
            if not self.connect_database():
                logger.error("Cannot start watchdog - database unavailable")
                return
                
            # Ensure bot is running
            if not self.is_bot_process_running():
                logger.info("Bot not running, starting it...")
                self.start_bot_process()
                
            # Start monitor
            self.start_monitor_process()
                
            # Main loop
            while self.running:
                self.run_once()
                time.sleep(interval)
                
        except Exception as e:
            logger.error(f"Watchdog error: {e}")
        finally:
            logger.info("Watchdog shutting down...")
            self.disconnect_database()
            
    def shutdown(self):
        """Shutdown the watchdog."""
        self.running = False


def main():
    """Main entry point for watchdog."""
    import argparse
    parser = argparse.ArgumentParser(description="Stonkers Trading Bot Watchdog")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Check interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--db-path",
        default="data/stonkers.db",
        help="Path to database file (default: data/stonkers.db)"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one check cycle and exit"
    )
    
    args = parser.parse_args()
    
    # Create and run watchdog
    watchdog = BotWatchdog(db_path=args.db_path)
    
    if args.once:
        watchdog.run_once()
    else:
        watchdog.run_continuously(interval=args.interval)


if __name__ == "__main__":
    main()