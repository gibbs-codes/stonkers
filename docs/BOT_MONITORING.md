# Stonkers Trading Bot Monitoring System

## Overview

The Stonkers trading bot now includes a comprehensive monitoring and restart mechanism to ensure high availability and prevent prolonged downtime. This system consists of:

1. **Health Monitor** - Checks bot status and logs health events
2. **Watchdog Service** - Automatically restarts the bot when it fails
3. **Heartbeat System** - Regular events to confirm the bot is operational
4. **Alerting System** - Notifications when issues are detected

## Components

### Health Monitor (`src/bot/health_monitor.py`)

The health monitor performs periodic checks to ensure the bot is functioning correctly:

- Checks if the bot process is running
- Verifies recent BOT_START events in the database
- Ensures the last start event was within 2 hours
- Logs health events to the database

#### Features:
- Configurable check intervals
- Automatic restart capability
- Cooldown periods to prevent rapid restart cycles
- Comprehensive logging

### Watchdog Service (`src/bot/watchdog.py`)

The watchdog service acts as a supervisor for the trading bot:

- Starts the bot process if not running
- Monitors bot health using the health monitor
- Kills and restarts unresponsive bot processes
- Runs the health monitor in a separate process
- Provides systemd integration for Linux deployments

#### Features:
- Continuous monitoring with configurable intervals
- Process lifecycle management
- Integration with system service managers
- Detailed logging and alerting

### Heartbeat System

The main bot now emits heartbeat events every 5 minutes:

- BOT_HEARTBEAT events logged to database
- Loop iteration counter for debugging
- Active trading pairs monitoring

### Alerting System

Alerts are generated when:

- BOT_START events are missing for >2 hours
- Bot process is not running
- Restart attempts exceed maximum limits
- Health checks consistently fail

## Configuration

### Monitoring Configuration (`config/monitoring.yaml`)

```yaml
# Health check settings
health_check:
  interval_seconds: 30          # Check every 30 seconds
  startup_timeout_hours: 2      # Alert if no start event in 2 hours
  max_failures_before_alert: 3  # Alert after 3 consecutive failures

# Restart settings
restart:
  max_attempts: 3               # Max 3 restart attempts
  cooldown_seconds: 300         # 5-minute cooldown between restarts
  auto_restart_enabled: true    # Enable automatic restarts

# Alert settings
alerts:
  email_notifications: false    # Email disabled by default
  min_severity: WARNING         # Minimum severity for alerts
```

## Deployment Options

### Docker Deployment

The bot can be deployed with watchdog monitoring using the special Dockerfile:

```bash
# Build with watchdog
docker build -t stonkers-watchdog -f Dockerfile.watchdog .

# Run with watchdog
docker run -d \
    --name stonkers-watchdog \
    --restart unless-stopped \
    --network gibbs-apps \
    -v $(pwd)/logs:/usr/src/app/logs:rw \
    -v $(pwd)/data:/usr/src/app/data:rw \
    --env-file .env \
    stonkers-watchdog:latest
```

### Systemd Service (Linux)

For Linux systems with systemd, deploy the watchdog as a service:

```bash
# Copy service file
sudo cp scripts/stonkers-watchdog.service /etc/systemd/system/

# Enable and start service
sudo systemctl enable stonkers-watchdog.service
sudo systemctl start stonkers-watchdog.service

# Check status
sudo systemctl status stonkers-watchdog.service
```

### Manual Script

Run the watchdog manually with the provided script:

```bash
# Make script executable
chmod +x scripts/start_bot_with_watchdog.sh

# Run the script
./scripts/start_bot_with_watchdog.sh
```

## Testing

Run the health monitor tests:

```bash
python -m pytest tests/test_health_monitor.py -v
```

## Events Logged

The monitoring system logs these events to the database:

- `BOT_START` - Bot started successfully
- `BOT_STOP` - Bot stopped normally
- `BOT_RESTART` - Restart initiated by monitor
- `BOT_RESTARTED` - Bot successfully restarted
- `BOT_HEALTH_ALERT` - Health check failed
- `BOT_WATCHDOG_ALERT` - Watchdog detected issues
- `BOT_HEARTBEAT` - Regular heartbeat signal
- `EXCEPTION` - Unhandled exceptions

## Troubleshooting

### Bot Won't Start

1. Check logs: `tail -f logs/watchdog.log`
2. Verify database connectivity
3. Check for port conflicts on dashboard port (3004)
4. Ensure API keys are configured properly

### Frequent Restarts

1. Check for exceptions in logs
2. Verify system resources (CPU, memory)
3. Check network connectivity to Alpaca
4. Review risk management settings

### Missing Heartbeats

1. Check main bot process is running
2. Verify database write permissions
3. Check for infinite loops in trading logic
4. Monitor system load and resource constraints