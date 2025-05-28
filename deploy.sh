
#!/bin/bash

# Telegram GitHub Release Uploader Bot - Deployment Script

set -e

echo "🚀 Deploying Telegram GitHub Release Uploader Bot..."

# Check if .env file exists
if [ ! -f .env ]; then
    echo "❌ .env file not found!"
    echo "Please copy .env.example to .env and configure it:"
    echo "cp .env.example .env"
    exit 1
fi

# Check if docker-compose is available
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose not found!"
    echo "Please install docker-compose to continue."
    exit 1
fi

# Stop existing containers
echo "🛑 Stopping existing containers..."
docker-compose down

# Build and start containers
echo "🔨 Building and starting containers..."
docker-compose up -d --build

# Wait a moment for containers to start
sleep 5

# Check container status
echo "📊 Container status:"
docker-compose ps

# Show logs
echo "📝 Recent logs:"
docker-compose logs --tail=20

echo "✅ Deployment complete!"
echo "🌐 Health check: http://localhost:5000"
echo "📋 View logs: docker-compose logs -f"
echo "🛑 Stop bot: docker-compose down"
