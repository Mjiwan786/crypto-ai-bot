#!/usr/bin/env bash

# Script to compile Protocol Buffer definitions for MCP.
# Requires that `protoc` is installed and available on your PATH.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"
protoc --python_out=. context.proto
echo "Protocol Buffers compiled successfully."