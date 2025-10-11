#!/usr/bin/env python3
"""
Enhanced Scalper Agent Test Runner

Comprehensive test runner that executes both testing and backtesting
for the enhanced scalper agent in the crypto-bot conda environment.
"""

import asyncio
import logging
import sys
import subprocess
import time
from pathlib import Path
from typing import Dict, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class EnhancedScalperTestRunner:
    """
    Comprehensive test runner for enhanced scalper agent
    """
    
    def __init__(self):
        """Initialize the test runner"""
        self.logger = None
        self.test_results = {}
        
    def setup_logging(self):
        """Setup logging for test runner"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.StreamHandler(),
                logging.FileHandler('logs/enhanced_scalper_test_runner.log')
            ]
        )
        self.logger = logging.getLogger(__name__)
        
    def run_command(self, command: str, description: str) -> bool:
        """Run a command and return success status"""
        self.logger.info(f"Running: {description}")
        try:
            result = subprocess.run(
                command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
                cwd=project_root
            )
            self.logger.info(f"✓ {description} completed successfully")
            if result.stdout:
                self.logger.debug(f"Output: {result.stdout}")
            return True
        except subprocess.CalledProcessError as e:
            self.logger.error(f"✗ {description} failed: {e}")
            if e.stderr:
                self.logger.error(f"Error: {e.stderr}")
            return False
    
    async def run_all_tests(self):
        """Run all test suites"""
        self.setup_logging()
        self.logger.info("=== Enhanced Scalper Agent Test Runner ===")
        
        # Test phases
        test_phases = [
            ("Configuration Validation", self.test_configuration),
            ("Unit Tests", self.test_unit_tests),
            ("Integration Tests", self.test_integration_tests),
            ("Performance Tests", self.test_performance_tests),
            ("Backtesting", self.test_backtesting),
            ("Stress Tests", self.test_stress_tests),
            ("Documentation Tests", self.test_documentation)
        ]
        
        total_phases = len(test_phases)
        passed_phases = 0
        
        for phase_name, phase_func in test_phases:
            self.logger.info(f"\n--- {phase_name} ---")
            try:
                success = await phase_func()
                if success:
                    passed_phases += 1
                    self.logger.info(f"✓ {phase_name} passed")
                else:
                    self.logger.error(f"✗ {phase_name} failed")
            except Exception as e:
                self.logger.error(f"✗ {phase_name} failed with exception: {e}")
        
        # Generate final report
        self.generate_final_report(total_phases, passed_phases)
        
        return passed_phases == total_phases
    
    async def test_configuration(self) -> bool:
        """Test configuration loading and validation"""
        self.logger.info("Testing configuration...")
        
        # Test configuration loading
        success = self.run_command(
            "conda run -n crypto-bot python -c \"from config.enhanced_scalper_loader import load_enhanced_scalper_config; config = load_enhanced_scalper_config(); print('Configuration loaded successfully')\"",
            "Configuration loading test"
        )
        
        if not success:
            return False
        
        # Test configuration validation
        success = self.run_command(
            "conda run -n crypto-bot python -c \"from config.enhanced_scalper_loader import EnhancedScalperConfigLoader; loader = EnhancedScalperConfigLoader(); config = loader.load_config(); loader._validate_config(config); print('Configuration validation passed')\"",
            "Configuration validation test"
        )
        
        return success
    
    async def test_unit_tests(self) -> bool:
        """Run unit tests"""
        self.logger.info("Running unit tests...")
        
        # Run pytest unit tests
        success = self.run_command(
            "conda run -n crypto-bot python -m pytest tests/test_enhanced_scalper.py -v --tb=short",
            "Unit tests"
        )
        
        return success
    
    async def test_integration_tests(self) -> bool:
        """Run integration tests"""
        self.logger.info("Running integration tests...")
        
        # Run integration test script
        success = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_integration.py",
            "Integration tests"
        )
        
        return success
    
    async def test_performance_tests(self) -> bool:
        """Run performance tests"""
        self.logger.info("Running performance tests...")
        
        # Run performance test script
        success = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite performance",
            "Performance tests"
        )
        
        return success
    
    async def test_backtesting(self) -> bool:
        """Run backtesting"""
        self.logger.info("Running backtesting...")
        
        # Run short backtest (1 month)
        success = self.run_command(
            "conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-01-31 --pairs BTC/USD ETH/USD --capital 10000",
            "Short backtest (1 month)"
        )
        
        if not success:
            return False
        
        # Run medium backtest (3 months)
        success = self.run_command(
            "conda run -n crypto-bot python scripts/backtest_enhanced_scalper.py --start-date 2024-01-01 --end-date 2024-03-31 --pairs BTC/USD ETH/USD --capital 10000",
            "Medium backtest (3 months)"
        )
        
        return success
    
    async def test_stress_tests(self) -> bool:
        """Run stress tests"""
        self.logger.info("Running stress tests...")
        
        # Run stress test script
        success = self.run_command(
            "conda run -n crypto-bot python scripts/test_enhanced_scalper.py --suite stress",
            "Stress tests"
        )
        
        return success
    
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
    
    def generate_final_report(self, total_phases: int, passed_phases: int):
        """Generate final test report"""
        self.logger.info("\n=== Enhanced Scalper Test Runner Report ===")
        self.logger.info(f"Total test phases: {total_phases}")
        self.logger.info(f"Passed phases: {passed_phases}")
        self.logger.info(f"Failed phases: {total_phases - passed_phases}")
        self.logger.info(f"Success rate: {passed_phases/total_phases:.1%}")
        
        if passed_phases == total_phases:
            self.logger.info("\n🎉 All tests passed! Enhanced scalper agent is ready for production.")
        else:
            self.logger.error(f"\n❌ {total_phases - passed_phases} test phases failed. Please review the logs.")
        
        # Save report to file
        report = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
            'total_phases': total_phases,
            'passed_phases': passed_phases,
            'failed_phases': total_phases - passed_phases,
            'success_rate': passed_phases / total_phases,
            'status': 'PASS' if passed_phases == total_phases else 'FAIL'
        }
        
        import json
        with open('logs/enhanced_scalper_test_runner_report.json', 'w') as f:
            json.dump(report, f, indent=2)
        
        self.logger.info(f"Test report saved to: logs/enhanced_scalper_test_runner_report.json")


async def main():
    """Main function"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Enhanced Scalper Agent Test Runner')
    parser.add_argument('--phase', type=str, help='Run specific test phase')
    parser.add_argument('--quick', action='store_true', help='Run quick tests only')
    
    args = parser.parse_args()
    
    # Create test runner
    runner = EnhancedScalperTestRunner()
    
    # Run tests
    if args.phase:
        # Run specific phase
        runner.setup_logging()
        if args.phase == 'config':
            success = await runner.test_configuration()
        elif args.phase == 'unit':
            success = await runner.test_unit_tests()
        elif args.phase == 'integration':
            success = await runner.test_integration_tests()
        elif args.phase == 'performance':
            success = await runner.test_performance_tests()
        elif args.phase == 'backtest':
            success = await runner.test_backtesting()
        elif args.phase == 'stress':
            success = await runner.test_stress_tests()
        elif args.phase == 'docs':
            success = await runner.test_documentation()
        else:
            print(f"Unknown test phase: {args.phase}")
            sys.exit(1)
        
        if success:
            print(f"✓ {args.phase} tests passed")
            sys.exit(0)
        else:
            print(f"✗ {args.phase} tests failed")
            sys.exit(1)
    else:
        # Run all tests
        success = await runner.run_all_tests()
        
        if success:
            print("\n🎉 All tests passed! Enhanced scalper agent is ready for production.")
            sys.exit(0)
        else:
            print("\n❌ Some tests failed. Please review the logs.")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

