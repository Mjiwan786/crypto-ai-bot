#!/bin/bash
# ===========================================
# CRYPTO AI BOT - STAGING PIPELINE WRAPPER
# ===========================================
# POSIX shell wrapper for staging pipeline supervisor
# 
# Usage:
#   bash scripts/run_staging.sh --env .env.staging --verbose
#   bash scripts/run_staging.sh --env .env.staging --include-exec --timeout 60

set -euo pipefail

# Default values
DOT_ENV_PATH=".env.staging"
TIMEOUT=30
INCLUDE_EXEC=false
VERBOSE=false

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --env)
            DOT_ENV_PATH="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --include-exec)
            INCLUDE_EXEC=true
            shift
            ;;
        --verbose)
            VERBOSE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --env PATH        Environment file path (default: .env.staging)"
            echo "  --timeout SECONDS Readiness timeout (default: 30)"
            echo "  --include-exec    Include execution agent in paper mode"
            echo "  --verbose         Enable verbose logging"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Change to project root
cd "$PROJECT_ROOT"

echo "==========================================="
echo "CRYPTO AI BOT - STAGING PIPELINE"
echo "==========================================="
echo ""

# Validate environment file
if [[ ! -f "$DOT_ENV_PATH" ]]; then
    echo "❌ Environment file not found: $DOT_ENV_PATH"
    echo "Please create $DOT_ENV_PATH from env.example"
    exit 1
fi

# Check if conda is available
if ! command -v conda &> /dev/null; then
    echo "❌ Conda not found in PATH"
    echo "Please install Anaconda or Miniconda and add to PATH"
    exit 1
fi

# Check if conda environment exists
echo "🔍 Checking conda environment 'crypto-bot'..."
if ! conda info --envs | grep -q "crypto-bot"; then
    echo "❌ Conda environment 'crypto-bot' not found"
    echo "Please create it with: conda create -n crypto-bot python=3.10"
    exit 1
fi
echo "✅ Conda environment 'crypto-bot' found"

# Initialize conda for this shell session
eval "$(conda shell.bash hook)"

# Activate conda environment
echo "🔄 Activating conda environment 'crypto-bot'..."
if ! conda activate crypto-bot; then
    echo "❌ Failed to activate conda environment"
    exit 1
fi
echo "✅ Conda environment activated"

# Check Python version
echo "🐍 Checking Python version..."
PYTHON_VERSION=$(python --version 2>&1)
echo "✅ $PYTHON_VERSION"

# Check required packages
echo "📦 Checking required packages..."
REQUIRED_PACKAGES=("redis" "yaml" "dotenv" "aiohttp" "websockets")
for package in "${REQUIRED_PACKAGES[@]}"; do
    if python -c "import $package" 2>/dev/null; then
        echo "✅ $package"
    else
        echo "⚠️  $package not found"
    fi
done

# Display configuration
echo ""
echo "Configuration:"
echo "  Environment: $DOT_ENV_PATH"
echo "  Timeout: $TIMEOUT seconds"
echo "  Include Execution: $INCLUDE_EXEC"
echo "  Verbose: $VERBOSE"
echo ""

# Build supervisor command
SUPERVISOR_CMD=("python" "scripts/run_staging.py" "--env" "$DOT_ENV_PATH" "--timeout" "$TIMEOUT")

if [[ "$INCLUDE_EXEC" == "true" ]]; then
    SUPERVISOR_CMD+=("--include-exec")
fi

if [[ "$VERBOSE" == "true" ]]; then
    SUPERVISOR_CMD+=("--verbose")
fi

# Run supervisor
echo "🚀 Starting staging pipeline supervisor..."
echo "Command: ${SUPERVISOR_CMD[*]}"
echo ""

# Trap signals for graceful shutdown
cleanup() {
    echo ""
    echo "🔄 Deactivating conda environment..."
    conda deactivate
    echo "✅ Cleanup completed"
}

trap cleanup EXIT INT TERM

# Execute supervisor
if "${SUPERVISOR_CMD[@]}"; then
    echo ""
    echo "✅ Staging pipeline completed successfully"
    exit 0
else
    EXIT_CODE=$?
    echo ""
    echo "❌ Staging pipeline failed with exit code $EXIT_CODE"
    exit $EXIT_CODE
fi

