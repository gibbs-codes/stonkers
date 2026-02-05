#!/bin/bash
# Manual deployment script for Stonkers on Raspberry Pi 5
# Use this if you want to deploy without GitHub Actions

set -e

DEPLOY_DIR=~/deployments/stonkers
SECRETS_DIR=~/secrets/stonkers

echo "=== Stonkers Manual Deployment ==="
echo ""

# Check for secrets
if [ ! -f "$SECRETS_DIR/production.env" ]; then
    echo "Error: Secrets file not found at $SECRETS_DIR/production.env"
    echo "Run setup-pi.sh first and configure your API keys."
    exit 1
fi

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(dirname "$SCRIPT_DIR")"

echo "Deploying from: $SOURCE_DIR"
echo "Deploying to: $DEPLOY_DIR"
echo ""

# Stop existing container
echo "1. Stopping existing container..."
docker stop stonkers-production 2>/dev/null || true
docker rm stonkers-production 2>/dev/null || true

# Backup database
if [ -f "$DEPLOY_DIR/data/stonkers.db" ]; then
    echo "2. Backing up database..."
    cp $DEPLOY_DIR/data/stonkers.db $DEPLOY_DIR/data/stonkers.db.backup
fi

# Create directories
mkdir -p $DEPLOY_DIR/logs
mkdir -p $DEPLOY_DIR/data

# Copy code (preserve logs and data)
echo "3. Copying application code..."
find $DEPLOY_DIR -mindepth 1 -maxdepth 1 ! -name 'logs' ! -name 'data' -exec rm -rf {} + 2>/dev/null || true
cp -r $SOURCE_DIR/* $DEPLOY_DIR/

# Copy secrets
echo "4. Copying secrets..."
cp $SECRETS_DIR/production.env $DEPLOY_DIR/.env

# Build image
echo "5. Building Docker image (this may take a few minutes on Pi)..."
cd $DEPLOY_DIR
docker build -t stonkers:latest .

# Run container
echo "6. Starting container..."
docker run -d \
    --name stonkers-production \
    --restart unless-stopped \
    --network gibbs-apps \
    --memory=1g \
    --memory-swap=2g \
    -v $(pwd)/logs:/usr/src/app/logs:rw \
    -v $(pwd)/data:/usr/src/app/data:rw \
    --env-file .env \
    stonkers:latest

# Wait and verify
echo "7. Verifying deployment..."
sleep 10
docker ps | grep stonkers-production

echo ""
echo "=== Deployment Complete ==="
echo ""
echo "View logs: docker logs -f stonkers-production"
