#!/bin/bash
# Setup logrotate configuration for crypto-ai-bot
# Usage: sudo bash scripts/setup_logrotate.sh /opt/crypto-ai-bot/logs

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    print_error "This script must be run as root (use sudo)"
    exit 1
fi

# Check arguments
if [[ $# -ne 1 ]]; then
    print_error "Usage: sudo bash scripts/setup_logrotate.sh <log_directory_path>"
    print_error "Example: sudo bash scripts/setup_logrotate.sh /opt/crypto-ai-bot/logs"
    exit 1
fi

LOG_DIR="$1"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOGROTATE_CONFIG_SOURCE="$PROJECT_ROOT/deploy/logrotate/crypto-ai-bot"
LOGROTATE_CONFIG_DEST="/etc/logrotate.d/crypto-ai-bot"

print_step "Setting up logrotate for crypto-ai-bot"
print_step "Log directory: $LOG_DIR"
print_step "Config source: $LOGROTATE_CONFIG_SOURCE"
print_step "Config destination: $LOGROTATE_CONFIG_DEST"

# Check if source config exists
if [[ ! -f "$LOGROTATE_CONFIG_SOURCE" ]]; then
    print_error "Source logrotate config not found: $LOGROTATE_CONFIG_SOURCE"
    exit 1
fi

# Create log directory if it doesn't exist
print_step "Creating log directory: $LOG_DIR"
mkdir -p "$LOG_DIR"
print_success "Log directory created/verified: $LOG_DIR"

# Set appropriate permissions on log directory
chmod 755 "$LOG_DIR"
print_success "Set permissions on log directory"

# Copy and patch the logrotate configuration
print_step "Installing logrotate configuration"
cp "$LOGROTATE_CONFIG_SOURCE" "$LOGROTATE_CONFIG_DEST"
print_success "Copied config to $LOGROTATE_CONFIG_DEST"

# Patch the path in the configuration
print_step "Patching log directory path in configuration"
sed -i "s|/opt/crypto-ai-bot/logs|$LOG_DIR|g" "$LOGROTATE_CONFIG_DEST"
print_success "Patched configuration with path: $LOG_DIR"

# Verify the patched configuration
print_step "Verifying patched configuration"
echo "--- Configuration content ---"
cat "$LOGROTATE_CONFIG_DEST"
echo "--- End configuration ---"

# Test the configuration with logrotate dry run
print_step "Testing configuration with logrotate dry run"
if logrotate -d "$LOGROTATE_CONFIG_DEST" > /dev/null 2>&1; then
    print_success "Logrotate configuration validation passed"
else
    print_error "Logrotate configuration validation failed"
    print_error "Running logrotate -d for details:"
    logrotate -d "$LOGROTATE_CONFIG_DEST" || true
    exit 1
fi

# Show dry run output for verification
print_step "Dry run output:"
logrotate -d "$LOGROTATE_CONFIG_DEST"

print_success "Logrotate setup completed successfully!"
print_success "Configuration installed to: $LOGROTATE_CONFIG_DEST"
print_success "Log directory: $LOG_DIR"
print_warning "Log rotation will begin automatically based on the weekly schedule"



