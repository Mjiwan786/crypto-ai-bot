#!/usr/bin/env bash
# ==============================================================================
# Bash Runner for Paper Local Publisher
# ==============================================================================
# Purpose: Start local publisher for SOL/USD and ADA/USD to signals:paper
# Created: 2025-11-08
# Usage: ./scripts/run_publisher_paper.sh
# ==============================================================================

set -euo pipefail  # Exit on error, undefined vars, pipe failures

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Banner
echo "======================================================================"
echo "PAPER LOCAL PUBLISHER - BASH RUNNER"
echo "======================================================================"
echo ""
echo "This will start a LOCAL publisher that adds SOL/USD and ADA/USD"
echo "to the PRODUCTION stream (signals:paper) alongside Fly.io"
echo ""
echo "Configuration:"
echo "  - Env File: .env.paper.local"
echo "  - Target Stream: signals:paper (PRODUCTION)"
echo "  - Base Pairs: BTC/USD, ETH/USD (from Fly.io)"
echo "  - Extra Pairs: SOL/USD, ADA/USD (from this local publisher)"
echo ""
echo "Safety:"
echo "  - Instant rollback: Press Ctrl+C to stop"
echo "  - No Fly.io changes required"
echo "  - Both publishers write to same stream"
echo ""
echo "======================================================================"
echo ""

# Change to project root directory (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

echo "Project root: $PROJECT_ROOT"
echo ""

# Step 1: Check conda environment
echo "[1/4] Checking conda environment..."
if conda env list | grep -q "crypto-bot"; then
    echo -e "${GREEN}[OK]${NC} Conda environment 'crypto-bot' found"
else
    echo -e "${RED}ERROR:${NC} Conda environment 'crypto-bot' not found!"
    echo "Please create it first: conda create -n crypto-bot python=3.10"
    exit 1
fi
echo ""

# Step 2: Verify .env.paper.local exists
echo "[2/4] Checking environment file..."
if [ ! -f ".env.paper.local" ]; then
    echo -e "${RED}ERROR:${NC} .env.paper.local not found!"
    echo "Expected location: $PROJECT_ROOT/.env.paper.local"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} .env.paper.local found"
echo ""

# Step 3: Verify Python script exists
echo "[3/4] Checking publisher script..."
if [ ! -f "run_paper_local_publisher.py" ]; then
    echo -e "${RED}ERROR:${NC} run_paper_local_publisher.py not found!"
    echo "Expected location: $PROJECT_ROOT/run_paper_local_publisher.py"
    exit 1
fi
echo -e "${GREEN}[OK]${NC} run_paper_local_publisher.py found"
echo ""

# Create logs directory if it doesn't exist
mkdir -p logs

# Step 4: Start publisher
echo "[4/4] Starting publisher..."
echo ""
echo "======================================================================"
echo "PUBLISHER STARTING"
echo "======================================================================"
echo ""
echo "Logs will be saved to: logs/paper_local_canary.txt"
echo ""
echo "To stop: Press Ctrl+C"
echo ""
echo "======================================================================"
echo ""

# Initialize conda for bash
eval "$(conda shell.bash hook)"

# Activate conda environment and run publisher
# Use tee to write to both console and log file
conda activate crypto-bot
python run_paper_local_publisher.py 2>&1 | tee logs/paper_local_canary.txt

# Capture exit code
EXIT_CODE=$?

echo ""
echo "======================================================================"
echo "PUBLISHER STOPPED"
echo "======================================================================"
echo "Exit code: $EXIT_CODE"
echo ""

if [ $EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}Publisher stopped cleanly${NC}"
else
    echo -e "${YELLOW}Publisher stopped with errors - check logs/paper_local_canary.txt${NC}"
fi

echo ""
