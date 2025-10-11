#!/bin/bash
# clean_repo.sh - Safe repository cleanup script for crypto-ai-bot
# This script removes development artifacts and caches without affecting source code

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
NC='\033[0m' # No Color

# Parse command line arguments
DRY_RUN=false
FORCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --force)
            FORCE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--dry-run] [--force]"
            echo "  --dry-run    Show what would be deleted without actually deleting"
            echo "  --force      Skip confirmation prompts"
            exit 0
            ;;
        *)
            echo "Unknown option $1"
            exit 1
            ;;
    esac
done

echo -e "${CYAN}🧹 Crypto AI Bot Repository Cleanup Script${NC}"
echo -e "${CYAN}=============================================${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}🔍 DRY RUN MODE - No files will be deleted${NC}"
fi

# Define cleanup targets (safe to remove)
cleanup_targets=(
    "**/__pycache__"
    ".pytest_cache"
    ".ruff_cache"
    ".benchmarks"
    "logs"
    "data/tmp"
    "**/*.pyc"
    "**/*.pyo"
    "**/*.pyd"
    "**/*.so"
    "**/*.egg-info"
    ".coverage"
    "htmlcov"
    "*.egg-info"
    "dist"
    "build"
)

total_size=0
file_count=0

# Function to format file size
format_size() {
    local size=$1
    if [ $size -gt 1048576 ]; then
        echo "$(echo "scale=2; $size / 1048576" | bc) MB"
    elif [ $size -gt 1024 ]; then
        echo "$(echo "scale=2; $size / 1024" | bc) KB"
    else
        echo "$size bytes"
    fi
}

# Function to get directory size
get_dir_size() {
    local dir=$1
    if [ -d "$dir" ]; then
        du -sb "$dir" 2>/dev/null | cut -f1 || echo "0"
    else
        echo "0"
    fi
}

# Function to get file size
get_file_size() {
    local file=$1
    if [ -f "$file" ]; then
        stat -f%z "$file" 2>/dev/null || stat -c%s "$file" 2>/dev/null || echo "0"
    else
        echo "0"
    fi
}

for pattern in "${cleanup_targets[@]}"; do
    # Use find to locate files/directories matching the pattern
    while IFS= read -r -d '' item; do
        if [ -e "$item" ]; then
            file_count=$((file_count + 1))
            
            if [ -d "$item" ]; then
                size=$(get_dir_size "$item")
            else
                size=$(get_file_size "$item")
            fi
            
            total_size=$((total_size + size))
            size_formatted=$(format_size $size)
            
            if [ "$DRY_RUN" = true ]; then
                echo -e "${YELLOW}Would remove: $item ($size_formatted)${NC}"
            else
                echo -e "${RED}Removing: $item ($size_formatted)${NC}"
                rm -rf "$item" 2>/dev/null || echo -e "${YELLOW}Warning: Failed to remove $item${NC}"
            fi
        fi
    done < <(find . -name "$pattern" -type f -o -name "$pattern" -type d -print0 2>/dev/null)
done

# Summary
total_size_formatted=$(format_size $total_size)

echo -e "\n${GREEN}📊 Cleanup Summary:${NC}"
echo -e "${WHITE}Files processed: $file_count${NC}"
echo -e "${WHITE}Total size: $total_size_formatted${NC}"

if [ "$DRY_RUN" = true ]; then
    echo -e "\n${CYAN}💡 To actually perform cleanup, run: ./scripts/clean_repo.sh${NC}"
else
    echo -e "\n${GREEN}✅ Cleanup completed!${NC}"
fi

# Conda environment check
echo -e "\n${CYAN}🐍 Conda Environment Check:${NC}"
if command -v conda &> /dev/null; then
    if conda info --envs 2>/dev/null | grep -q "crypto-bot"; then
        echo -e "${GREEN}✅ Found conda environment: crypto-bot${NC}"
    else
        echo -e "${YELLOW}⚠️  Conda environment 'crypto-bot' not found${NC}"
        echo -e "${CYAN}   Create it with: conda create -n crypto-bot python=3.11${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Conda not available or not in PATH${NC}"
fi

# Redis connection check
echo -e "\n${CYAN}🔴 Redis Connection Check:${NC}"
echo -e "${WHITE}Redis Cloud URL: redis://default:***@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818${NC}"
echo -e "${CYAN}Note: Use --tls --cacert <path_to_ca_certfile> for secure connection${NC}"

echo -e "\n${CYAN}🎯 Next steps:${NC}"
echo -e "${WHITE}1. Activate conda environment: conda activate crypto-bot${NC}"
echo -e "${WHITE}2. Install dependencies: pip install -r requirements.txt${NC}"
echo -e "${WHITE}3. Test Redis connection: python scripts/check_redis_tls.py${NC}"

