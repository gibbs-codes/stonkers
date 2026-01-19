#!/bin/bash
# Quick test script for Alpaca connection

# Colors for output
GREEN='\033[0;32m'
NC='\033[0m' # No Color

echo -e "${GREEN}🧪 Testing Alpaca Connection${NC}"
echo ""

# Activate venv
source venv/bin/activate

# Run smoke test
python test_alpaca_connection.py
