#!/bin/bash
# Bash script to start the complete trading system

echo "🚀 Starting Crypto AI Trading System..."
echo

# Set environment variables (modify as needed)
export ENVIRONMENT="production"
export REDIS_URL="redis://localhost:6379"
export KRAKEN_API_KEY="your_api_key_here"
export KRAKEN_API_SECRET="your_api_secret_here"

# Change to project directory
cd "$(dirname "$0")/.."

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 not found. Please install Python 3.8+ and add it to PATH."
    exit 1
fi

echo "✅ Python found: $(python3 --version)"

# Check if virtual environment exists
if [ -f "venv/bin/activate" ]; then
    echo "🔧 Activating virtual environment..."
    source venv/bin/activate
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "📦 Installing dependencies..."
    pip install -r requirements.txt
fi

# Start the trading system
echo "🚀 Starting trading system..."
python3 scripts/start_trading_system.py --environment "$ENVIRONMENT"

# Check exit status
if [ $? -ne 0 ]; then
    echo "❌ Trading system failed to start."
    exit 1
fi
