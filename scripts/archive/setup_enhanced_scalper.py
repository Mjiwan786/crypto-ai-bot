#!/usr/bin/env python3
"""
Enhanced Scalper Setup Script

Sets up the enhanced scalper agent with all integrations in the crypto-bot conda environment.
"""

import logging
import os
import subprocess
import sys


def setup_logging():
    """Setup logging for the setup script"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    return logging.getLogger(__name__)

def run_command(command, description, logger):
    """Run a command and log the result"""
    logger.info(f"Running: {description}")
    try:
        result = subprocess.run(command, shell=True, check=True, capture_output=True, text=True)
        logger.info(f"✓ {description} completed successfully")
        if result.stdout:
            logger.debug(f"Output: {result.stdout}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"✗ {description} failed: {e}")
        if e.stderr:
            logger.error(f"Error: {e.stderr}")
        return False

def check_conda_env(logger):
    """Check if crypto-bot conda environment exists"""
    logger.info("Checking conda environment...")
    
    try:
        result = subprocess.run(
            "conda env list | grep crypto-bot", 
            shell=True, 
            capture_output=True, 
            text=True
        )
        
        if "crypto-bot" in result.stdout:
            logger.info("✓ crypto-bot conda environment found")
            return True
        else:
            logger.warning("crypto-bot conda environment not found")
            return False
    except Exception as e:
        logger.error(f"Error checking conda environment: {e}")
        return False

def activate_conda_env():
    """Activate the crypto-bot conda environment"""
    # This will be handled by the conda run command
    return "conda run -n crypto-bot"

def install_dependencies(logger):
    """Install required dependencies"""
    logger.info("Installing enhanced scalper dependencies...")
    
    # Install additional requirements
    requirements_file = "requirements_enhanced_scalper.txt"
    if os.path.exists(requirements_file):
        success = run_command(
            f"{activate_conda_env()} pip install -r {requirements_file}",
            "Installing enhanced scalper requirements",
            logger
        )
        if not success:
            return False
    else:
        logger.warning(f"Requirements file {requirements_file} not found")
    
    # Install TA-Lib (common issue)
    logger.info("Installing TA-Lib...")
    run_command(
        f"{activate_conda_env()} pip install TA-Lib",
        "Installing TA-Lib",
        logger
    )
    
    # If TA-Lib fails, try talib-binary
    if not run_command(
        f"{activate_conda_env()} python -c 'import talib'",
        "Testing TA-Lib import",
        logger
    ):
        logger.info("TA-Lib installation failed, trying talib-binary...")
        run_command(
            f"{activate_conda_env()} pip install talib-binary",
            "Installing talib-binary",
            logger
        )
    
    return True

def create_directories(logger):
    """Create necessary directories"""
    logger.info("Creating necessary directories...")
    
    directories = [
        "logs",
        "data",
        "reports/enhanced_scalper",
        "config/backups"
    ]
    
    for directory in directories:
        os.makedirs(directory, exist_ok=True)
        logger.info(f"✓ Created directory: {directory}")

def setup_configuration(logger):
    """Setup configuration files"""
    logger.info("Setting up configuration...")
    
    # Check if enhanced scalper config exists
    config_file = "config/enhanced_scalper_config.yaml"
    if not os.path.exists(config_file):
        logger.warning(f"Configuration file {config_file} not found")
        logger.info("Please ensure the enhanced scalper configuration is properly set up")
        return False
    
    logger.info(f"✓ Configuration file found: {config_file}")
    return True

def run_tests(logger):
    """Run tests to verify installation"""
    logger.info("Running tests to verify installation...")
    
    # Run unit tests
    success = run_command(
        f"{activate_conda_env()} python -m pytest tests/test_enhanced_scalper.py -v",
        "Running enhanced scalper unit tests",
        logger
    )
    
    if not success:
        logger.warning("Unit tests failed, but continuing with setup...")
    
    # Run integration tests
    success = run_command(
        f"{activate_conda_env()} python scripts/test_enhanced_integration.py",
        "Running enhanced scalper integration tests",
        logger
    )
    
    if not success:
        logger.warning("Integration tests failed, but continuing with setup...")
    
    return True

def create_demo_script(logger):
    """Create a demo script for easy testing"""
    demo_script = """#!/bin/bash
# Enhanced Scalper Demo Script

echo "Starting Enhanced Scalper Demo..."
echo "This will run a 10-minute demo of the enhanced scalper agent"
echo "Press Ctrl+C to stop early"
echo ""

conda run -n crypto-bot python scripts/run_enhanced_scalper.py --duration 10 --pairs BTC/USD ETH/USD

echo ""
echo "Demo completed!"
"""
    
    with open("run_enhanced_scalper_demo.sh", "w") as f:
        f.write(demo_script)
    
    os.chmod("run_enhanced_scalper_demo.sh", 0o755)
    logger.info("✓ Created demo script: run_enhanced_scalper_demo.sh")

def main():
    """Main setup function"""
    logger = setup_logging()
    
    logger.info("=== Enhanced Scalper Setup ===")
    logger.info("Setting up enhanced scalper agent with multi-strategy integration")
    
    # Check conda environment
    if not check_conda_env(logger):
        logger.error("crypto-bot conda environment not found!")
        logger.error("Please create the conda environment first:")
        logger.error("  conda create -n crypto-bot python=3.10")
        logger.error("  conda activate crypto-bot")
        sys.exit(1)
    
    # Create directories
    create_directories(logger)
    
    # Setup configuration
    if not setup_configuration(logger):
        logger.error("Configuration setup failed!")
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies(logger):
        logger.error("Dependency installation failed!")
        sys.exit(1)
    
    # Run tests
    run_tests(logger)
    
    # Create demo script
    create_demo_script(logger)
    
    logger.info("=== Setup Complete ===")
    logger.info("Enhanced scalper agent is ready to use!")
    logger.info("")
    logger.info("Next steps:")
    logger.info("1. Review configuration: config/enhanced_scalper_config.yaml")
    logger.info("2. Run demo: ./run_enhanced_scalper_demo.sh")
    logger.info("3. Run integration tests: conda run -n crypto-bot python scripts/test_enhanced_integration.py")
    logger.info("4. Start trading: conda run -n crypto-bot python scripts/run_enhanced_scalper.py --duration 60")
    logger.info("")
    logger.info("For more information, see: docs/ENHANCED_SCALPER_README.md")

if __name__ == "__main__":
    main()

