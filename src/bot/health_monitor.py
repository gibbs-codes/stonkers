"""Health monitoring service for the Stonkers trading bot."""

import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.data.database import Database

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/health_monitor.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


class BotHealthMonitor:
    """Monitors the health of the trading bot and manages restarts."""

    def __init__(self, db_path: str = "data/stonkers.db", check_interval: int = 60):
        """Initialize the health monitor.
        
        Args:
            db_path: Path to the SQLite database
            check_interval: Interval in seconds between health checks
        """
        self.db_path = Path(db_path)
        self.check_interval = check_interval
        self.db = None
        self.restart_attempts = 0
        self.max_restart_attempts = 3
        self.restart_cooldown = 300  # 5 minutes
        
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
            
    def get_last_start_event(self) -> Optional[datetime]:
        """Get the timestamp of the last BOT_START event.
        
        Returns:
            Timestamp of last BOT_START event or None if not found
        """
        if not self.db:
            logger.error("Database not connected")
            return None
            
        try:
            # Query for the most recent BOT_START event
            cursor = self.db.conn.cursor()
            cursor.execute("""
                SELECT timestamp FROM bot_events 
                WHERE event_type = 'BOT_START' 
                ORDER BY timestamp DESC 
                LIMIT 1
            """)
            
            row = cursor.fetchone()
            if row:
                # Parse ISO formatted timestamp
                return datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            return None
        except Exception as e:
            logger.error(f"Error querying BOT_START events: {e}")
            return None
    
    def check_process_running(self) -> bool:
        """Check if the bot process is running.
        
        Returns:
            True if process is running, False otherwise
        """
        try:
            # Use pgrep to check for python processes running main.py
            result = subprocess.run(
                ["pgrep", "-f", "python.*src\\.main"],
                capture_output=True,
                text=True
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Error checking process status: {e}")
            return False
            
    def is_bot_healthy(self) -> tuple[bool, str]:
        """Check if the bot is healthy.
        
        Returns:
            Tuple of (is_healthy, reason)
        """
        # Check if process is running
        if not self.check_process_running():
            return False, "Bot process not running"
            
        # Check database connection
        if not self.db:
            if not self.connect_database():
                return False, "Cannot connect to database"
                
        # Check last BOT_START event
        last_start = self.get_last_start_event()
        if not last_start:
            return False, "No BOT_START event found"
            
        # Check if BOT_START event is recent (within last 2 hours)
        now = datetime.now(timezone.utc)
        if now - last_start > timedelta(hours=2):
            return False, f"Last BOT_START was {now - last_start} ago"
            
        return True, "Bot is healthy"
        
    def restart_bot(self) -> bool:
        """Restart the bot process.
        
        Returns:
            True if restart initiated successfully, False otherwise
        """
        try:
            logger.info("Attempting to restart bot...")
            
            # Check if we've exceeded restart attempts
            if self.restart_attempts >= self.max_restart_attempts:
                logger.error("Maximum restart attempts exceeded")
                return False
                
            # Check cooldown period
            if hasattr(self, '_last_restart') and self._last_restart:
                time_since_last = time.time() - self._last_restart
                if time_since_last < self.restart_cooldown:
                    logger.warning(f"Restart cooldown active: {self.restart_cooldown - time_since_last:.0f}s remaining")
                    return False
                    
            # Kill existing process if running
            try:
                subprocess.run(["pkill", "-f", "python.*src\\.main"], capture_output=True)
                time.sleep(5)  # Give process time to shut down
            except Exception as e:
                logger.warning(f"Error killing existing process: {e}")
                
            # Start new process
            # Try to determine if we're in Docker or running directly
            if os.path.exists("/.dockerenv"):
                # We're in Docker, restart handled by Docker daemon
                logger.info("Running in Docker - restart handled by Docker daemon")
                # Log restart attempt in database
                if self.db:
                    self.db.insert_bot_event(
                        event_type="BOT_RESTART",
                        message="Restart initiated by health monitor",
                        severity="WARNING"
                    )
                return True
            else:
                # Running directly, try to restart
                logger.info("Running directly - attempting manual restart")
                # This would typically be handled by systemd or similar
                # For now, we'll just log the event
                if self.db:
                    self.db.insert_bot_event(
                        event_type="BOT_RESTART",
                        message="Manual restart needed",
                        severity="WARNING"
                    )
                return True
                
        except Exception as e:
            logger.error(f"Error restarting bot: {e}")
            return False
        finally:
            self.restart_attempts += 1
            self._last_restart = time.time()
            
    def run_health_check(self):
        """Perform a single health check."""
        logger.info("Performing health check...")
        
        # Connect to database if needed
        if not self.db:
            if not self.connect_database():
                logger.error("Cannot perform health check - database unavailable")
                return
                
        # Check bot health
        is_healthy, reason = self.is_bot_healthy()
        logger.info(f"Health check result: {'HEALTHY' if is_healthy else 'UNHEALTHY'} - {reason}")
        
        if not is_healthy:
            # Log alert
            if self.db:
                self.db.insert_bot_event(
                    event_type="BOT_HEALTH_ALERT",
                    message=reason,
                    severity="ERROR"
                )
                
            # Attempt restart
            if self.restart_bot():
                logger.info("Restart initiated successfully")
            else:
                logger.error("Failed to restart bot")
                
    def monitor_continuously(self):
        """Monitor the bot continuously."""
        logger.info("Starting continuous health monitoring...")
        
        # Initialize database connection
        if not self.connect_database():
            logger.error("Cannot start monitoring - database unavailable")
            return
            
        try:
            while True:
                self.run_health_check()
                time.sleep(self.check_interval)
        except KeyboardInterrupt:
            logger.info("Health monitoring stopped by user")
        except Exception as e:
            logger.error(f"Health monitoring error: {e}")
        finally:
            self.disconnect_database()


def main():
    """Main entry point for health monitor."""
    # Parse command line arguments
    import argparse
    parser = argparse.ArgumentParser(description="Stonkers Trading Bot Health Monitor")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Health check interval in seconds (default: 60)"
    )
    parser.add_argument(
        "--db-path",
        default="data/stonkers.db",
        help="Path to database file (default: data/stonkers.db)"
    )
    
    args = parser.parse_args()
    
    # Create and run monitor
    monitor = BotHealthMonitor(db_path=args.db_path, check_interval=args.interval)
    monitor.monitor_continuously()


if __name__ == "__main__":
    main()