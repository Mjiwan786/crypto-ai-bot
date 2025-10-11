#!/usr/bin/env python3
"""
Conda Environment Setup Script

This script sets up the conda environment for the complete trading system
with all required dependencies.
"""

import subprocess
import sys
import logging
from pathlib import Path

def setup_logging():
    """Setup logging"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )

def run_command(cmd, description):
    """Run a command and handle errors"""
    logger = logging.getLogger("CondaSetup")
    logger.info(f"🔄 {description}...")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info(f"✅ {description} completed successfully")
            if result.stdout:
                logger.debug(f"Output: {result.stdout}")
            return True
        else:
            logger.error(f"❌ {description} failed")
            logger.error(f"Error: {result.stderr}")
            return False
            
    except Exception as e:
        logger.error(f"❌ {description} failed with exception: {e}")
        return False

def check_conda_installed():
    """Check if conda is installed"""
    logger = logging.getLogger("CondaSetup")
    logger.info("🔍 Checking if conda is installed...")
    
    try:
        result = subprocess.run(["conda", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            logger.info(f"✅ Conda found: {result.stdout.strip()}")
            return True
        else:
            logger.error("❌ Conda not found")
            return False
    except FileNotFoundError:
        logger.error("❌ Conda not found in PATH")
        return False

def create_conda_environment():
    """Create conda environment"""
    logger = logging.getLogger("CondaSetup")
    
    # Check if environment already exists
    logger.info("🔍 Checking if conda environment 'crypto-bot' exists...")
    
    try:
        result = subprocess.run(
            ["conda", "info", "--envs"], 
            capture_output=True, 
            text=True
        )
        
        if "crypto-bot" in result.stdout:
            logger.info("✅ Conda environment 'crypto-bot' already exists")
            return True
    except Exception as e:
        logger.warning(f"Could not check existing environments: {e}")
    
    # Create environment
    cmd = "conda create -n crypto-bot python=3.9 -y"
    return run_command(cmd, "Creating conda environment 'crypto-bot'")

def install_dependencies():
    """Install required dependencies"""
    logger = logging.getLogger("CondaSetup")
    
    # Activate environment and install dependencies
    commands = [
        "conda activate crypto-bot && conda install -c conda-forge redis-py -y",
        "conda activate crypto-bot && conda install -c conda-forge pandas -y",
        "conda activate crypto-bot && conda install -c conda-forge numpy -y",
        "conda activate crypto-bot && conda install -c conda-forge scikit-learn -y",
        "conda activate crypto-bot && conda install -c conda-forge matplotlib -y",
        "conda activate crypto-bot && conda install -c conda-forge seaborn -y",
        "conda activate crypto-bot && conda install -c conda-forge jupyter -y",
        "conda activate crypto-bot && conda install -c conda-forge pytest -y",
        "conda activate crypto-bot && conda install -c conda-forge pytest-asyncio -y",
        "conda activate crypto-bot && pip install ccxt",
        "conda activate crypto-bot && pip install langgraph",
        "conda activate crypto-bot && pip install pydantic",
        "conda activate crypto-bot && pip install pyyaml",
        "conda activate crypto-bot && pip install asyncio-mqtt",
        "conda activate crypto-bot && pip install websockets",
        "conda activate crypto-bot && pip install aiohttp",
        "conda activate crypto-bot && pip install python-dotenv"
    ]
    
    success = True
    for cmd in commands:
        if not run_command(cmd, f"Installing dependency: {cmd.split()[-1]}"):
            success = False
    
    return success

def install_project_dependencies():
    """Install project-specific dependencies"""
    logger = logging.getLogger("CondaSetup")
    
    # Check if requirements.txt exists
    requirements_file = Path("requirements.txt")
    if requirements_file.exists():
        cmd = "conda activate crypto-bot && pip install -r requirements.txt"
        return run_command(cmd, "Installing project dependencies from requirements.txt")
    else:
        logger.warning("requirements.txt not found, skipping project dependencies")
        return True

def verify_installation():
    """Verify the installation"""
    logger = logging.getLogger("CondaSetup")
    logger.info("🔍 Verifying installation...")
    
    # Test Python import
    test_imports = [
        "import pandas",
        "import numpy", 
        "import redis",
        "import ccxt",
        "import pydantic",
        "import yaml",
        "import pytest"
    ]
    
    success = True
    for test_import in test_imports:
        cmd = f"conda activate crypto-bot && python -c \"{test_import}\""
        if not run_command(cmd, f"Testing import: {test_import.split()[-1]}"):
            success = False
    
    return success

def main():
    """Main setup function"""
    setup_logging()
    logger = logging.getLogger("CondaSetup")
    
    logger.info("🚀 Starting Conda Environment Setup for Crypto AI Trading System")
    logger.info("="*70)
    
    # Check conda installation
    if not check_conda_installed():
        logger.error("❌ Conda is not installed. Please install Anaconda or Miniconda first.")
        sys.exit(1)
    
    # Create environment
    if not create_conda_environment():
        logger.error("❌ Failed to create conda environment")
        sys.exit(1)
    
    # Install dependencies
    if not install_dependencies():
        logger.error("❌ Failed to install dependencies")
        sys.exit(1)
    
    # Install project dependencies
    if not install_project_dependencies():
        logger.error("❌ Failed to install project dependencies")
        sys.exit(1)
    
    # Verify installation
    if not verify_installation():
        logger.error("❌ Installation verification failed")
        sys.exit(1)
    
    logger.info("="*70)
    logger.info("✅ Conda environment setup completed successfully!")
    logger.info("")
    logger.info("To activate the environment, run:")
    logger.info("  conda activate crypto-bot")
    logger.info("")
    logger.info("To run the trading system, use:")
    logger.info("  python scripts/start_trading_system.py")
    logger.info("")
    logger.info("To run integration tests, use:")
    logger.info("  python scripts/run_integration_tests.py")

if __name__ == "__main__":
    main()
