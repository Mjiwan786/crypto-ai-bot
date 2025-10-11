#!/usr/bin/env python3
"""
Integration Test Runner for Complete Trading System

This script runs comprehensive integration tests for the complete trading system
within the conda environment.
"""

import asyncio
import logging
import sys
import subprocess
from pathlib import Path
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def setup_logging():
    """Setup logging for test runner"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

def run_pytest_tests(test_path: str = "tests/test_complete_system_integration.py", verbose: bool = True):
    """Run pytest tests"""
    logger = logging.getLogger("TestRunner")
    
    cmd = ["python", "-m", "pytest", test_path]
    if verbose:
        cmd.append("-v")
    cmd.extend(["--tb=short", "--asyncio-mode=auto"])
    
    logger.info(f"Running pytest tests: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        
        print("STDOUT:")
        print(result.stdout)
        
        if result.stderr:
            print("STDERR:")
            print(result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        logger.error(f"Failed to run pytest tests: {e}")
        return False

def run_health_check():
    """Run health check tests"""
    logger = logging.getLogger("TestRunner")
    
    cmd = ["python", "scripts/health_check.py", "--format", "text"]
    
    logger.info(f"Running health check: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        
        print("Health Check Output:")
        print(result.stdout)
        
        if result.stderr:
            print("Health Check Errors:")
            print(result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        logger.error(f"Failed to run health check: {e}")
        return False

def run_configuration_validation():
    """Run configuration validation"""
    logger = logging.getLogger("TestRunner")
    
    cmd = ["python", "scripts/start_trading_system.py", "--validate-only", "--environment", "test"]
    
    logger.info(f"Running configuration validation: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=project_root)
        
        print("Configuration Validation Output:")
        print(result.stdout)
        
        if result.stderr:
            print("Configuration Validation Errors:")
            print(result.stderr)
        
        return result.returncode == 0
        
    except Exception as e:
        logger.error(f"Failed to run configuration validation: {e}")
        return False

def run_system_tests():
    """Run system integration tests"""
    logger = logging.getLogger("TestRunner")
    
    # Test 1: Configuration validation
    logger.info("🔍 Running configuration validation...")
    config_ok = run_configuration_validation()
    
    # Test 2: Health check
    logger.info("🏥 Running health check...")
    health_ok = run_health_check()
    
    # Test 3: Pytest integration tests
    logger.info("🧪 Running pytest integration tests...")
    pytest_ok = run_pytest_tests()
    
    # Summary
    logger.info("\n" + "="*60)
    logger.info("📊 INTEGRATION TEST SUMMARY")
    logger.info("="*60)
    logger.info(f"Configuration Validation: {'✅ PASS' if config_ok else '❌ FAIL'}")
    logger.info(f"Health Check: {'✅ PASS' if health_ok else '❌ FAIL'}")
    logger.info(f"Pytest Tests: {'✅ PASS' if pytest_ok else '❌ FAIL'}")
    
    overall_success = config_ok and health_ok and pytest_ok
    logger.info(f"Overall Result: {'✅ ALL TESTS PASSED' if overall_success else '❌ SOME TESTS FAILED'}")
    logger.info("="*60)
    
    return overall_success

def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Run integration tests for the trading system")
    parser.add_argument("--test-type", "-t", default="all",
                       choices=["all", "config", "health", "pytest"],
                       help="Type of tests to run")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Enable verbose output")
    parser.add_argument("--test-file", "-f", default="tests/test_complete_system_integration.py",
                       help="Specific test file to run")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging()
    logger = logging.getLogger("TestRunner")
    
    logger.info("🚀 Starting Integration Test Runner")
    logger.info(f"Test type: {args.test_type}")
    logger.info(f"Verbose: {args.verbose}")
    
    success = False
    
    try:
        if args.test_type == "all":
            success = run_system_tests()
        elif args.test_type == "config":
            success = run_configuration_validation()
        elif args.test_type == "health":
            success = run_health_check()
        elif args.test_type == "pytest":
            success = run_pytest_tests(args.test_file, args.verbose)
        
        if success:
            logger.info("✅ All tests completed successfully")
            sys.exit(0)
        else:
            logger.error("❌ Some tests failed")
            sys.exit(1)
            
    except Exception as e:
        logger.error(f"❌ Test runner failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
