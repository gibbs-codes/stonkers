#!/bin/bash
# Quick start script for Stonkers trading bot

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}🚀 Starting Stonkers Trading Bot${NC}"
echo ""

# Check if venv exists
if [ ! -d "venv" ]; then
    echo -e "${YELLOW}⚠️  Virtual environment not found. Creating it...${NC}"
    python3 -m venv venv
    source venv/bin/activate
    pip install -r requirements.txt
else
    # Activate venv
    source venv/bin/activate
fi

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}⚠️  .env file not found${NC}"
    echo "Please create .env file with your Alpaca API keys:"
    echo "  cp .env.example .env"
    echo "  # Then edit .env with your keys"
    exit 1
fi

# Run the bot
echo -e "${GREEN}Starting bot...${NC}"
python -m src.main
