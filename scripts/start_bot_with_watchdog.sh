#!/bin/bash
# Script to start the Stonkers trading bot with watchdog monitoring

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Starting Stonkers Bot with Watchdog ==="

# Create logs directory if it doesn't exist
mkdir -p $PROJECT_DIR/logs

# Change to project directory
cd $PROJECT_DIR

# Start the watchdog in the background
echo "Starting watchdog service..."
nohup python -m src.bot.watchdog --interval 60 > logs/watchdog.log 2>&1 &

echo "Watchdog started with PID $!"
echo "Logs are being written to logs/watchdog.log"
echo "Bot should start automatically if not already running."

# Show status
sleep 2
echo ""
echo "=== Status ==="
pgrep -af "python.*src\.bot\.watchdog" && echo "Watchdog: RUNNING" || echo "Watchdog: NOT RUNNING"
pgrep -af "python.*src\.main" && echo "Bot: RUNNING" || echo "Bot: NOT RUNNING"