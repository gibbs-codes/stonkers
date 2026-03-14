"""Tests for the health monitoring service."""

import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone, timedelta
import tempfile
import os
import sys

# Add src to path for imports
sys.path.insert(0, 'src')


class TestBotHealthMonitor(unittest.TestCase):
    """Test cases for BotHealthMonitor."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock logging to avoid file creation issues
        self.patcher1 = patch('logging.FileHandler')
        self.patcher2 = patch('logging.basicConfig')
        self.patcher1.start()
        self.patcher2.start()
        
        # Now we can import the module
        from src.bot.health_monitor import BotHealthMonitor
        self.BotHealthMonitor = BotHealthMonitor
        
        # Create a temporary database file for testing
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
    def tearDown(self):
        """Clean up test fixtures."""
        # Remove temporary database file
        if os.path.exists(self.temp_db.name):
            os.unlink(self.temp_db.name)
            
        # Stop patches
        self.patcher1.stop()
        self.patcher2.stop()
            
    @patch('src.bot.health_monitor.Database')
    def test_connect_database_success(self, mock_database):
        """Test successful database connection."""
        # Setup mock
        mock_db_instance = MagicMock()
        mock_database.return_value = mock_db_instance
        
        # Create monitor
        monitor = self.BotHealthMonitor(db_path=self.temp_db.name)
        
        # Test connection
        result = monitor.connect_database()
        
        # Assertions
        self.assertTrue(result)
        mock_database.assert_called_once_with(self.temp_db.name)
        self.assertEqual(monitor.db, mock_db_instance)
        
    @patch('src.bot.health_monitor.Database')
    def test_connect_database_failure(self, mock_database):
        """Test failed database connection."""
        # Setup mock to raise exception
        mock_database.side_effect = Exception("Connection failed")
        
        # Create monitor with non-existent database
        monitor = self.BotHealthMonitor(db_path="/nonexistent/path.db")
        
        # Test connection
        result = monitor.connect_database()
        
        # Assertions
        self.assertFalse(result)
        self.assertIsNone(monitor.db)
        
    @patch('src.bot.health_monitor.subprocess.run')
    def test_check_process_running_success(self, mock_subprocess):
        """Test successful process running check."""
        # Setup mock to return success
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_subprocess.return_value = mock_result
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        
        # Test process check
        result = monitor.check_process_running()
        
        # Assertions
        self.assertTrue(result)
        mock_subprocess.assert_called_once_with(
            ["pgrep", "-f", "python.*src\\.main"],
            capture_output=True,
            text=True
        )
        
    @patch('src.bot.health_monitor.subprocess.run')
    def test_check_process_running_failure(self, mock_subprocess):
        """Test failed process running check."""
        # Setup mock to return failure
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_subprocess.return_value = mock_result
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        
        # Test process check
        result = monitor.check_process_running()
        
        # Assertions
        self.assertFalse(result)
        
    @patch('src.bot.health_monitor.Database')
    def test_get_last_start_event_found(self, mock_database):
        """Test successful retrieval of last start event."""
        # Setup mock database with a recent BOT_START event
        mock_db_instance = MagicMock()
        mock_cursor = MagicMock()
        mock_db_instance.conn.cursor.return_value = mock_cursor
        
        # Mock the query result
        timestamp = datetime.now(timezone.utc).isoformat()
        mock_cursor.fetchone.return_value = {'timestamp': timestamp}
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        monitor.db = mock_db_instance
        
        # Test retrieval
        result = monitor.get_last_start_event()
        
        # Assertions
        self.assertIsNotNone(result)
        mock_cursor.execute.assert_called_once()
        mock_cursor.fetchone.assert_called_once()
        
    @patch('src.bot.health_monitor.Database')
    def test_get_last_start_event_not_found(self, mock_database):
        """Test when no start event is found."""
        # Setup mock database with no BOT_START event
        mock_db_instance = MagicMock()
        mock_cursor = MagicMock()
        mock_db_instance.conn.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = None
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        monitor.db = mock_db_instance
        
        # Test retrieval
        result = monitor.get_last_start_event()
        
        # Assertions
        self.assertIsNone(result)
        
    @patch('src.bot.health_monitor.Database')
    @patch('src.bot.health_monitor.BotHealthMonitor.check_process_running')
    def test_is_bot_healthy_success(self, mock_check_process, mock_database):
        """Test successful bot health check."""
        # Setup mocks
        mock_check_process.return_value = True
        
        mock_db_instance = MagicMock()
        mock_cursor = MagicMock()
        mock_db_instance.conn.cursor.return_value = mock_cursor
        
        # Mock recent BOT_START event
        recent_time = datetime.now(timezone.utc) - timedelta(minutes=30)
        mock_cursor.fetchone.return_value = {'timestamp': recent_time.isoformat()}
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        monitor.db = mock_db_instance
        
        # Test health check
        is_healthy, reason = monitor.is_bot_healthy()
        
        # Assertions
        self.assertTrue(is_healthy)
        self.assertEqual(reason, "Bot is healthy")
        
    @patch('src.bot.health_monitor.Database')
    @patch('src.bot.health_monitor.BotHealthMonitor.check_process_running')
    def test_is_bot_healthy_process_not_running(self, mock_check_process, mock_database):
        """Test bot health when process is not running."""
        # Setup mocks
        mock_check_process.return_value = False
        
        # Create monitor
        monitor = self.BotHealthMonitor()
        
        # Test health check
        is_healthy, reason = monitor.is_bot_healthy()
        
        # Assertions
        self.assertFalse(is_healthy)
        self.assertEqual(reason, "Bot process not running")


if __name__ == '__main__':
    unittest.main()