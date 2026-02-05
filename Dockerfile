# Stonkers Trading Bot Dockerfile
# Compatible with ARM64 (Raspberry Pi 5) and AMD64
FROM python:3.11-slim

# Set working directory
WORKDIR /usr/src/app

# Install system dependencies (includes build tools for ARM64 compilation)
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
# Use --prefer-binary to avoid compiling from source when possible
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Copy application code
COPY . .

# Create logs directory
RUN mkdir -p logs

# Environment variables (will be overridden by docker run --env-file)
ENV PYTHONUNBUFFERED=1
ENV PAPER_TRADING=true

# Health check - check if process is running
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD pgrep -f "python -m src.main" || exit 1

# Run the bot
CMD ["python", "-m", "src.main"]
