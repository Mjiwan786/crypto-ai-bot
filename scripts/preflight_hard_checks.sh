#!/bin/bash
# =============================================================================
# Crypto AI Bot - Preflight Hard Checks (Linux/macOS Bash Wrapper)
# =============================================================================
# Activates conda environment and runs preflight checks
# Exit codes: 0 = success, 1 = failure

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
GRAY='\033[0;37m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_SCRIPT="$SCRIPT_DIR/preflight_hard_checks.py"

echo -e "${CYAN}[Preflight] Linux/macOS bash wrapper starting...${NC}"
echo -e "${GRAY}[Preflight] Project root: $PROJECT_ROOT${NC}"

# Change to project root directory
cd "$PROJECT_ROOT"

# Check if Python script exists
if [[ ! -f "$PYTHON_SCRIPT" ]]; then
    echo -e "${RED}❌ Python preflight script not found: $PYTHON_SCRIPT${NC}"
    exit 1
fi

# Make Python script executable
chmod +x "$PYTHON_SCRIPT"

# Conda environment name
CONDA_ENV="crypto-bot"
CONDA_ACTIVATED=false

# Function to check if conda is available
check_conda() {
    if command -v conda >/dev/null 2>&1; then
        echo -e "${GREEN}[Preflight] Conda is available${NC}"
        return 0
    else
        echo -e "${YELLOW}⚠️  Conda not available, trying system Python...${NC}"
        return 1
    fi
}

# Function to activate conda environment
activate_conda() {
    local env_name="$1"
    
    # Check if environment exists
    if conda env list | grep -q "^$env_name "; then
        echo -e "${YELLOW}[Preflight] Activating conda environment: $env_name${NC}"
        
        # Initialize conda for this shell
        eval "$(conda shell.bash hook)"
        
        # Activate environment
        conda activate "$env_name"
        
        if [[ "$CONDA_DEFAULT_ENV" == "$env_name" ]]; then
            echo -e "${GREEN}[Preflight] Successfully activated conda environment: $env_name${NC}"
            CONDA_ACTIVATED=true
            return 0
        else
            echo -e "${YELLOW}⚠️  Failed to activate conda environment: $env_name${NC}"
            return 1
        fi
    else
        echo -e "${YELLOW}⚠️  Conda environment '$env_name' not found${NC}"
        return 1
    fi
}

# Function to run preflight with current Python
run_preflight() {
    local python_cmd="$1"
    local verbose_flag=""
    
    # Add verbose flag if requested
    if [[ "${1:-}" == "--verbose" ]] || [[ "${2:-}" == "--verbose" ]]; then
        verbose_flag="--verbose"
    fi
    
    echo -e "${CYAN}[Preflight] Running preflight checks...${NC}"
    
    # Check Python version
    local python_version
    python_version=$($python_cmd --version 2>&1)
    echo -e "${GRAY}[Preflight] Python version: $python_version${NC}"
    
    # Run preflight script
    if $python_cmd "$PYTHON_SCRIPT" $verbose_flag; then
        echo -e "${GREEN}[Preflight] All checks passed!${NC}"
        return 0
    else
        echo -e "${RED}[Preflight] Some checks failed!${NC}"
        return 1
    fi
}

# Main execution
main() {
    # Check for verbose flag
    local verbose_flag=""
    if [[ "${1:-}" == "--verbose" ]] || [[ "${1:-}" == "-v" ]]; then
        verbose_flag="--verbose"
    fi
    
    # Try conda first
    if check_conda; then
        if activate_conda "$CONDA_ENV"; then
            # Run with conda environment
            run_preflight "python" "$verbose_flag"
            exit $?
        else
            echo -e "${YELLOW}⚠️  Conda activation failed, trying system Python...${NC}"
        fi
    fi
    
    # Fallback to system Python
    echo -e "${YELLOW}[Preflight] Using system Python...${NC}"
    
    # Check if Python is available
    if command -v python3 >/dev/null 2>&1; then
        run_preflight "python3" "$verbose_flag"
        exit $?
    elif command -v python >/dev/null 2>&1; then
        run_preflight "python" "$verbose_flag"
        exit $?
    else
        echo -e "${RED}❌ Python not found in PATH${NC}"
        exit 1
    fi
}

# Run main function with all arguments
main "$@"
