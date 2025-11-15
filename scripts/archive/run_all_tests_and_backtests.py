#!/usr/bin/env python3
"""
Enhanced Scalper Agent - Complete Test and Backtest Runner

This script runs all tests and backtests for the enhanced scalper agent
in the crypto-bot conda environment, providing a comprehensive validation.
"""

import asyncio
import json
import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class CompleteTestRunner:
    """
    Complete test and backtest runner for enhanced scalper agent
    """
    
    def __init__(self):
        """Initialize the test runner"""
        self.logger = None
        self.test_results = {}
        self.start_time = None
        
    def setup_logging(self):
        """Setup logging for test runner"""
        # Create logs directory
        Path('logs').mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/complete_test_runner.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def run_command(self, command: str, description: str, timeout: int = 300) -> Dict[str, Any]:
        """Run a command and return detailed results"""
        self.logger.info(f"Running: {description}")
        start_time = time.time()
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                cwd=project_root,
                timeout=timeout
            )
            
            duration = time.time() - start_time
            self.logger.info(f"✓ {description} completed successfully in {duration:.1f}s")
            
            return {
                'status': 'PASS',
                'duration': duration,
                'stdout': result.stdout,
                'stderr': result.stderr
            }
            
        except subprocess.CalledProcessError as e:
            duration = time.time() - start_time
            self.logger.error(f"✗ {description} failed after {duration:.1f}s: {e}")
            
            return {
                'status': 'FAIL',
                'duration': duration,
                'stdout': e.stdout,
                'stderr': e.stderr,
                'error': str(e)
            }
            
        except subprocess.TimeoutExpired as e:
            duration = time.time() - start_time
            self.logger.error(f"✗ {description} timed out after {duration:.1f}s")
            
            return {
                'status': 'TIMEOUT',
                'duration': duration,
                'stdout': e.stdout,
                'stderr': e.stderr,
                'error': 'Command timed out'
            }
    
    async def run_complete_test_suite(self):
        """Run the complete test suite"""
        self.setup_logging()
        self.start_time = time.time()
        
        self.logger.info("=== Enhanced Scalper Agent - Complete Test Suite ===")
        self.logger.info("This will run all tests and backtests for comprehensive validation")
        
        # Test phases
        test_phases = [
            ("Environment Check", self.check_environment),
            ("Configuration Tests", self.test_configuration),
            ("Unit Tests", self.test_unit_tests),
            ("Integration Tests", self.test_integration_tests),
            ("Performance Tests", self.test_performance_tests),
            ("Short Backtest", self.test_short_backtest),
            ("Medium Backtest", self.test_medium_backtest),
            ("Long Backtest", self.test_long_backtest),
            ("Stress Tests", self.test_stress_tests),
            ("Documentation Tests", self.test_documentation),
            ("Demo Test", self.test_demo)
        ]
        
        total_phases = len(test_phases)
        passed_phases = 0
        
        for phase_name, phase_func in test_phases:
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"Phase: {phase_name}")
            self.logger.info(f"{'='*60}")
            
            try:
                success = await phase_func()
                if success:
                    passed_phases += 1
                    self.logger.info(f"✓ {phase_name} PASSED")
                else:
                    self.logger.error(f"✗ {phase_name} FAILED")
            except Exception as e:
                self.logger.error(f"✗ {phase_name} FAILED with exception: {e}")
        
        # Generate comprehensive report
        self.generate_comprehensive_report(total_phases, passed_phases)
        
        return passed_phases == total_phases
    
    async def check_environment(self) -> bool:
        """Check if the environment is properly set up"""
        self.logger.info("Checking environment setup...")
        
        # Check conda environment
        result = self.run_command(
            "conda info --envs | grep crypto-bot",
            "Check crypto-bot conda environment"
        )
        
        if result['status'] != 'PASS':
            self.logger.error("crypto-bot conda environment not found!")
            return False
        
        # Check Python version
        result = self.run_command(
            "conda run -n crypto-bot python --version",
            "Check Python version"
        )
        
        if result['status'] != 'PASS':
            self.logger.error("Python version check failed!")
            return False
        
        # Check required packages
        required_packages = [
            'pandas', 'numpy', 'asyncio', 'ccxt', 'pydantic', 'redis'
        ]
        
        for package in required_packages:
            result = self.run_command(
                f"conda run -n crypto-bot python -c \"import {package}; print('{package} available')\"",
                f"Check {package} package"
            )
            
            if result['status'] != 'PASS':
                self.logger.warning(f"Package {package} may not be available")
        
        return True
    
    async def test_configuration(self) -> bool:
        """Test configuration loading and validation"""
        self.logger.info("Testing configuration...")
        
        # Test configuration loading
        result = self.run_command(
            "conda run -n crypto-bot python -c \"from config.enhanced_scalper_loader import load_enhanced_scalper_config; config = load_enhanced_scalper_config(); print('Configuration loaded successfully')\"",
            "Configuration loading test"
        )
        
        if result['status'] != 'PASS':
            return False
        
        # Test configuration validation
        result = self.run_command(
            "conda run -n crypto-bot python -c \"from config.enhanced_scalper_loader import EnhancedScalperConfigLoader; loader = EnhancedScalperConfigLoader(); config = loader.load_config(); loader._validate_config(config); print('Configuration validation passed')\"",
            "Configuration validation test"
        )
        
        return result['status'] == 'PASS'
    
    async def test_unit_tests(self) -> bool:
        """Run unit tests"""
        self.logger.info("Running unit tests...")
        
        result = self.run_command(
            "conda run -n crypto-bot python -m pytest tests/test_enhanced_scalper.py -v --tb=short --durations=10",
            "Unit tests with timing"
        )
        
        return result['status'] == 'PASS'
    
    async def test_integration_tests(self) -> bool:
        """Run integration tests"""
        self.logger.info("Running integration tests...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_integration.py",
            "Integration tests"
        )
        
        return result['status'] == 'PASS'
    
    async def test_performance_tests(self) -> bool:
        """Run performance tests"""
        self.logger.info("Running performance tests...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite performance",
            "Performance tests"
        )
        
        return result['status'] == 'PASS'
    
    async def test_short_backtest(self) -> bool:
        """Run short backtest (1 week)"""
        self.logger.info("Running short backtest (1 week)...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-07 --pairs BTC/USD ETH/USD --capital 10000",
            "Short backtest (1 week)"
        )
        
        return result['status'] == 'PASS'
    
    async def test_medium_backtest(self) -> bool:
        """Run medium backtest (1 month)"""
        self.logger.info("Running medium backtest (1 month)...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-31 --pairs BTC/USD ETH/USD --capital 10000",
            "Medium backtest (1 month)"
        )
        
        return result['status'] == 'PASS'
    
    async def test_long_backtest(self) -> bool:
        """Run long backtest (3 months)"""
        self.logger.info("Running long backtest (3 months)...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-03-31 --pairs BTC/USD ETH/USD --capital 10000",
            "Long backtest (3 months)"
        )
        
        return result['status'] == 'PASS'
    
    async def test_stress_tests(self) -> bool:
        """Run stress tests"""
        self.logger.info("Running stress tests...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite stress",
            "Stress tests"
        )
        
        return result['status'] == 'PASS'
    
    async def test_documentation(self) -> bool:
        """Test documentation"""
        self.logger.info("Testing documentation...")
        
        # Check if documentation files exist
        doc_files = [
            "docs/ENHANCED_SCALPER_README.md",
            "ENHANCED_SCALPER_INTEGRATION_SUMMARY.md",
            "config/enhanced_scalper_config.yaml",
            "requirements_enhanced_scalper.txt"
        ]
        
        all_exist = True
        for doc_file in doc_files:
            if not Path(doc_file).exists():
                self.logger.error(f"Documentation file missing: {doc_file}")
                all_exist = False
            else:
                self.logger.info(f"✓ {doc_file} exists")
        
        return all_exist
    
    async def test_demo(self) -> bool:
        """Test demo functionality"""
        self.logger.info("Testing demo functionality...")
        
        result = self.run_command(
            "conda run -n crypto-bot python scripts/demo_enhanced_scalper.py --duration 2",
            "Demo test (2 minutes)"
        )
        
        return result['status'] == 'PASS'
    
    def generate_comprehensive_report(self, total_phases: int, passed_phases: int):
        """Generate comprehensive test report"""
        total_time = time.time() - self.start_time
        
        self.logger.info("\n" + "="*80)
        self.logger.info("ENHANCED SCALPER AGENT - COMPREHENSIVE TEST REPORT")
        self.logger.info("="*80)
        
        self.logger.info(f"Test execution time: {total_time/60:.1f} minutes")
        self.logger.info(f"Total test phases: {total_phases}")
        self.logger.info(f"Passed phases: {passed_phases}")
        self.logger.info(f"Failed phases: {total_phases - passed_phases}")
        self.logger.info(f"Success rate: {passed_phases/total_phases:.1%}")
        
        # Detailed results
        self.logger.info("\nDetailed Results:")
        for phase_name, result in self.test_results.items():
            status = result['status']
            duration = result.get('duration', 0)
            self.logger.info(f"  {phase_name}: {status} ({duration:.1f}s)")
            
            if status == 'FAIL' and 'error' in result:
                self.logger.error(f"    Error: {result['error']}")
        
        # Summary
        if passed_phases == total_phases:
            self.logger.info("\n🎉 ALL TESTS PASSED!")
            self.logger.info("The enhanced scalper agent is fully validated and ready for production.")
            self.logger.info("All integrations are working correctly.")
        else:
            self.logger.error(f"\n❌ {total_phases - passed_phases} TEST PHASES FAILED!")
            self.logger.error("Please review the failed tests and fix the issues.")
            self.logger.error("The enhanced scalper agent may not be ready for production.")
        
        # Save comprehensive report
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_time_minutes': total_time / 60,
            'total_phases': total_phases,
            'passed_phases': passed_phases,
            'failed_phases': total_phases - passed_phases,
            'success_rate': passed_phases / total_phases,
            'status': 'PASS' if passed_phases == total_phases else 'FAIL',
            'detailed_results': self.test_results
        }
        
        with open('logs/comprehensive_test_report.json', 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        self.logger.info("\nComprehensive report saved to: logs/comprehensive_test_report.json")
        self.logger.info("="*80)


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent - Complete Test Suite')
    parser.add_argument('--quick', action='store_true', help='Run quick tests only (skip long backtests)')
    parser.add_argument('--phase', type=str, help='Run specific test phase only')
    
    args = parser.parse_args()
    
    # Create test runner
    runner = CompleteTestRunner()
    
    # Run tests
    if args.phase:
        # Run specific phase
        runner.setup_logging()
        if args.phase == 'env':
            success = await runner.check_environment()
        elif args.phase == 'config':
            success = await runner.test_configuration()
        elif args.phase == 'unit':
            success = await runner.test_unit_tests()
        elif args.phase == 'integration':
            success = await runner.test_integration_tests()
        elif args.phase == 'performance':
            success = await runner.test_performance_tests()
        elif args.phase == 'short-backtest':
            success = await runner.test_short_backtest()
        elif args.phase == 'medium-backtest':
            success = await runner.test_medium_backtest()
        elif args.phase == 'long-backtest':
            success = await runner.test_long_backtest()
        elif args.phase == 'stress':
            success = await runner.test_stress_tests()
        elif args.phase == 'docs':
            success = await runner.test_documentation()
        elif args.phase == 'demo':
            success = await runner.test_demo()
        else:
            print(f"Unknown test phase: {args.phase}")
            print("Available phases: env, config, unit, integration, performance, short-backtest, medium-backtest, long-backtest, stress, docs, demo")
            sys.exit(1)
        
        if success:
            print(f"✓ {args.phase} tests passed")
            sys.exit(0)
        else:
            print(f"✗ {args.phase} tests failed")
            sys.exit(1)
    else:
        # Run complete test suite
        success = await runner.run_complete_test_suite()
        
        if success:
            print("\n🎉 ALL TESTS PASSED!")
            print("The enhanced scalper agent is fully validated and ready for production.")
            sys.exit(0)
        else:
            print("\n❌ SOME TESTS FAILED!")
            print("Please review the logs and fix the issues.")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

