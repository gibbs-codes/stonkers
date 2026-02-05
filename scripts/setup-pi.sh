#!/bin/bash
# Raspberry Pi 5 Setup Script for Stonkers Trading Bot
# Run this on your Pi to prepare for deployment

set -e

echo "=== Stonkers Pi 5 Setup ==="
echo ""

# Check if running on ARM64
ARCH=$(uname -m)
if [[ "$ARCH" != "aarch64" ]]; then
    echo "Warning: This script is designed for ARM64 (Raspberry Pi 5)"
    echo "Detected architecture: $ARCH"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

echo "1. Updating system packages..."
sudo apt-get update
sudo apt-get upgrade -y

echo ""
echo "2. Installing Docker..."
if command -v docker &> /dev/null; then
    echo "Docker already installed: $(docker --version)"
else
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed. You may need to log out and back in for group changes."
fi

echo ""
echo "3. Creating directory structure..."
mkdir -p ~/deployments/stonkers/logs
mkdir -p ~/deployments/stonkers/data
mkdir -p ~/secrets/stonkers

echo ""
echo "4. Setting up Docker network..."
docker network create gibbs-apps 2>/dev/null || echo "Network gibbs-apps already exists"

echo ""
echo "5. Creating secrets template..."
if [ ! -f ~/secrets/stonkers/production.env ]; then
    cat > ~/secrets/stonkers/production.env << 'EOF'
# Stonkers Production Environment
# Fill in your Alpaca API credentials

ALPACA_API_KEY=your_api_key_here
ALPACA_SECRET_KEY=your_secret_key_here

# Optional: Set to 'false' for live trading (be careful!)
PAPER_TRADING=true
EOF
    echo "Created ~/secrets/stonkers/production.env"
    echo "IMPORTANT: Edit this file with your Alpaca API credentials!"
else
    echo "Secrets file already exists at ~/secrets/stonkers/production.env"
fi

echo ""
echo "=== Setup Complete ==="
echo ""
echo "Next steps:"
echo "1. Edit ~/secrets/stonkers/production.env with your Alpaca API keys"
echo "2. Set up GitHub Actions self-hosted runner:"
echo "   - Go to your repo Settings > Actions > Runners > New self-hosted runner"
echo "   - Select Linux ARM64 and follow the instructions"
echo ""
echo "3. Once runner is configured, push to main branch to deploy!"
echo ""
echo "Useful commands:"
echo "  View logs:     docker logs -f stonkers-production"
echo "  Stop bot:      docker stop stonkers-production"
echo "  Start bot:     docker start stonkers-production"
echo "  Restart bot:   docker restart stonkers-production"
echo "  Check status:  docker ps | grep stonkers"
