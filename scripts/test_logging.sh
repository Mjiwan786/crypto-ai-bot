#!/bin/bash
# Test logging functionality
# Verifies that the logging system works correctly by writing test logs and checking file output

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

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

# Get script directory and project root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_FILE="$PROJECT_ROOT/logs/crypto_ai_bot.log"

print_step "Testing logging functionality"
print_info "Project root: $PROJECT_ROOT"
print_info "Log file: $LOG_FILE"

# Create logs directory if it doesn't exist
print_step "Ensuring logs directory exists"
mkdir -p "$PROJECT_ROOT/logs"

# Get initial log file size (if it exists)
INITIAL_SIZE=0
if [[ -f "$LOG_FILE" ]]; then
    INITIAL_SIZE=$(wc -c < "$LOG_FILE")
    print_info "Initial log file size: $INITIAL_SIZE bytes"
else
    print_info "Log file does not exist yet, will be created"
fi

# Create Python script to test logging
print_step "Creating test logging script"
cat > "$PROJECT_ROOT/test_logging_temp.py" << 'EOF'
#!/usr/bin/env python3
"""Temporary script to test logging functionality."""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from utils.logger import get_logger

# Get logger
logger = get_logger(__name__)

# Write 200 INFO lines
print("Writing 200 INFO log entries...")
for i in range(1, 201):
    logger.info(f"Test INFO message {i:03d} - This is a test log entry for verification")

# Write 10 ERROR lines
print("Writing 10 ERROR log entries...")
for i in range(1, 11):
    logger.error(f"Test ERROR message {i:02d} - This is a test error for verification")

print("Logging test completed")
EOF

# Run the Python logging test
print_step "Running logging test"
cd "$PROJECT_ROOT"
python3 test_logging_temp.py

# Clean up temporary file
rm -f test_logging_temp.py

# Verify log file exists and grew in size
print_step "Verifying log file"
if [[ ! -f "$LOG_FILE" ]]; then
    print_error "Log file was not created: $LOG_FILE"
    exit 1
fi

FINAL_SIZE=$(wc -c < "$LOG_FILE")
print_info "Final log file size: $FINAL_SIZE bytes"

if [[ $FINAL_SIZE -le $INITIAL_SIZE ]]; then
    print_error "Log file did not grow in size (initial: $INITIAL_SIZE, final: $FINAL_SIZE)"
    exit 1
fi

# Count log entries to verify they were written
print_step "Verifying log entries"
INFO_COUNT=$(grep -c "Test INFO message" "$LOG_FILE" || echo "0")
ERROR_COUNT=$(grep -c "Test ERROR message" "$LOG_FILE" || echo "0")

print_info "INFO entries found: $INFO_COUNT"
print_info "ERROR entries found: $ERROR_COUNT"

if [[ $INFO_COUNT -lt 200 ]]; then
    print_error "Expected 200 INFO entries, found $INFO_COUNT"
    exit 1
fi

if [[ $ERROR_COUNT -lt 10 ]]; then
    print_error "Expected 10 ERROR entries, found $ERROR_COUNT"
    exit 1
fi

# Show sample log entries
print_step "Sample log entries (last 5 lines)"
tail -5 "$LOG_FILE"

print_success "Logging test completed successfully!"
print_success "OK: logging works"
