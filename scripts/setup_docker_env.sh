#!/bin/bash
# ===============================================
# Docker Environment Setup Script
# ===============================================
# This script helps set up the Docker environment for crypto AI bot

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if .env files exist
check_env_files() {
    log_info "Checking environment files..."
    
    if [ ! -f ".env.staging" ]; then
        log_warn ".env.staging not found, creating from template..."
        cp env.staging.template .env.staging
        log_success "Created .env.staging from template"
    else
        log_success ".env.staging exists"
    fi
    
    if [ ! -f ".env.prod" ]; then
        log_warn ".env.prod not found, creating from template..."
        cp env.prod.template .env.prod
        log_success "Created .env.prod from template"
    else
        log_success ".env.prod exists"
    fi
}

# Validate environment configuration
validate_staging() {
    log_info "Validating staging configuration..."
    
    if [ -f ".env.staging" ]; then
        # Check if PAPER_TRADING_ENABLED is set to true
        if grep -q "PAPER_TRADING_ENABLED=true" .env.staging; then
            log_success "Staging: PAPER_TRADING_ENABLED=true ✓"
        else
            log_error "Staging: PAPER_TRADING_ENABLED should be true"
            return 1
        fi
        
        # Check if LIVE_TRADING_CONFIRMATION is blank
        if grep -q "LIVE_TRADING_CONFIRMATION=$" .env.staging; then
            log_success "Staging: LIVE_TRADING_CONFIRMATION is blank ✓"
        else
            log_warn "Staging: LIVE_TRADING_CONFIRMATION should be blank for staging"
        fi
        
        # Check if ENVIRONMENT is staging
        if grep -q "ENVIRONMENT=staging" .env.staging; then
            log_success "Staging: ENVIRONMENT=staging ✓"
        else
            log_error "Staging: ENVIRONMENT should be staging"
            return 1
        fi
    else
        log_error ".env.staging not found"
        return 1
    fi
}

validate_production() {
    log_info "Validating production configuration..."
    
    if [ -f ".env.prod" ]; then
        # Check if PAPER_TRADING_ENABLED is set to false
        if grep -q "PAPER_TRADING_ENABLED=false" .env.prod; then
            log_success "Production: PAPER_TRADING_ENABLED=false ✓"
        else
            log_error "Production: PAPER_TRADING_ENABLED should be false"
            return 1
        fi
        
        # Check if LIVE_TRADING_CONFIRMATION is set
        if grep -q "LIVE_TRADING_CONFIRMATION=I CONFIRM LIVE TRADING ENABLED" .env.prod; then
            log_success "Production: LIVE_TRADING_CONFIRMATION is set ✓"
        else
            log_warn "Production: LIVE_TRADING_CONFIRMATION should be set for live trading"
        fi
        
        # Check if ENVIRONMENT is production
        if grep -q "ENVIRONMENT=production" .env.prod; then
            log_success "Production: ENVIRONMENT=production ✓"
        else
            log_error "Production: ENVIRONMENT should be production"
            return 1
        fi
    else
        log_error ".env.prod not found"
        return 1
    fi
}

# Test Docker Compose configuration
test_docker_compose() {
    log_info "Testing Docker Compose configuration..."
    
    # Test staging profile
    log_info "Testing staging profile..."
    if docker-compose --profile staging config > /dev/null 2>&1; then
        log_success "Staging profile configuration is valid"
    else
        log_error "Staging profile configuration is invalid"
        return 1
    fi
    
    # Test production profile
    log_info "Testing production profile..."
    if docker-compose --profile prod config > /dev/null 2>&1; then
        log_success "Production profile configuration is valid"
    else
        log_error "Production profile configuration is invalid"
        return 1
    fi
}

# Create logs directory
create_logs_directory() {
    log_info "Creating logs directory..."
    mkdir -p logs
    log_success "Logs directory created"
}

# Show usage instructions
show_usage() {
    echo ""
    log_info "Docker Compose Usage:"
    echo ""
    echo "  # Start staging (PAPER trading)"
    echo "  docker-compose --profile staging up -d"
    echo ""
    echo "  # Start production (LIVE trading - requires confirmation)"
    echo "  docker-compose --profile prod up -d"
    echo ""
    echo "  # View logs"
    echo "  docker-compose --profile staging logs -f bot"
    echo "  docker-compose --profile prod logs -f bot-prod"
    echo ""
    echo "  # Stop services"
    echo "  docker-compose --profile staging down"
    echo "  docker-compose --profile prod down"
    echo ""
    echo "  # Health check"
    echo "  docker-compose exec bot python scripts/healthcheck.py"
    echo "  docker-compose exec bot-prod python scripts/healthcheck.py"
    echo ""
}

# Main function
main() {
    echo "==============================================="
    echo "Crypto AI Bot - Docker Environment Setup"
    echo "==============================================="
    
    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        log_error "Docker is not running. Please start Docker and try again."
        exit 1
    fi
    
    # Check if Docker Compose is available
    if ! command -v docker-compose > /dev/null 2>&1; then
        log_error "Docker Compose is not installed. Please install Docker Compose and try again."
        exit 1
    fi
    
    # Setup environment
    check_env_files
    create_logs_directory
    
    # Validate configurations
    if validate_staging; then
        log_success "Staging configuration is valid"
    else
        log_error "Staging configuration validation failed"
        exit 1
    fi
    
    if validate_production; then
        log_success "Production configuration is valid"
    else
        log_error "Production configuration validation failed"
        exit 1
    fi
    
    # Test Docker Compose
    if test_docker_compose; then
        log_success "Docker Compose configuration is valid"
    else
        log_error "Docker Compose configuration validation failed"
        exit 1
    fi
    
    log_success "Environment setup completed successfully!"
    show_usage
}

# Run main function
main "$@"



