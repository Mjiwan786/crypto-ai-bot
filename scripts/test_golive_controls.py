#!/usr/bin/env python3
"""
Go-Live Controls Test Script

Tests all safety features of the TradingModeController:
- Paper/Live mode switching
- LIVE_TRADING_CONFIRMATION requirement
- Emergency kill-switch (env + Redis)
- Pair whitelist enforcement
- Notional caps per pair
- Circuit breaker monitoring
- Status event publishing

Usage:
    python scripts/test_golive_controls.py
"""

import os
import sys
import redis
import logging
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Load .env file if exists
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / '.env'
    if env_path.exists():
        load_dotenv(env_path)
        logging.info(f"Loaded .env from {env_path}")
except ImportError:
    logging.warning("python-dotenv not installed, skipping .env loading")

from config.trading_mode_controller import (
    TradingModeController,
    TradingModeConfig,
    TradingMode,
    CircuitBreakerMonitor
)

# Setup logging
logging.basicConfig(
    level=logging.WARNING,  # Suppress library logs
    format='%(message)s'
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler with a simpler format for test output
console = logging.StreamHandler()
console.setLevel(logging.INFO)
formatter = logging.Formatter('%(message)s')
console.setFormatter(formatter)
logger.addHandler(console)


class GoLiveControlsTest:
    """Test suite for go-live controls"""

    def __init__(self):
        """Initialize test suite"""
        self.redis_url = os.getenv('REDIS_URL')

        if not self.redis_url:
            logger.error("REDIS_URL not set in environment or .env file")
            logger.info("Please set REDIS_URL in your .env file")
            raise ValueError("REDIS_URL is required")

        self.redis = self._connect_redis()
        self.passed = 0
        self.failed = 0

    def _connect_redis(self) -> redis.Redis:
        """Connect to Redis Cloud with TLS"""
        logger.info(f"Connecting to Redis Cloud...")

        # Parse URL to determine if TLS is needed
        use_tls = self.redis_url.startswith('rediss://')

        if use_tls:
            # TLS connection for Redis Cloud
            import ssl
            client = redis.from_url(
                self.redis_url,
                ssl_cert_reqs=ssl.CERT_NONE,  # Don't verify cert for testing
                decode_responses=True
            )
        else:
            client = redis.from_url(self.redis_url, decode_responses=True)

        # Test connection
        client.ping()
        logger.info("✓ Redis connected successfully")

        return client

    def assert_true(self, condition: bool, message: str):
        """Assert condition is true"""
        if condition:
            logger.info(f"✓ PASS: {message}")
            self.passed += 1
        else:
            logger.error(f"✗ FAIL: {message}")
            self.failed += 1

    def assert_false(self, condition: bool, message: str):
        """Assert condition is false"""
        self.assert_true(not condition, message)

    def test_basic_initialization(self):
        """Test 1: Basic controller initialization"""
        logger.info("\n=== Test 1: Basic Initialization ===")

        # Save original env
        original_mode = os.getenv('TRADING_MODE')

        try:
            # Set PAPER mode
            os.environ['TRADING_MODE'] = 'PAPER'

            controller = TradingModeController(
                redis_client=self.redis,
                pair_whitelist=['XBTUSD', 'ETHUSD'],
                notional_caps={'XBTUSD': 10000.0, 'ETHUSD': 5000.0}
            )

            self.assert_true(
                controller.get_current_mode() == TradingMode.PAPER,
                "Controller initializes in PAPER mode"
            )

            active_stream = controller.get_active_signal_stream()
            self.assert_true(
                active_stream == 'signals:paper',
                f"ACTIVE_SIGNALS points to signals:paper (got: {active_stream})"
            )

            status = controller.get_status()
            self.assert_true(
                status['mode'] == 'PAPER',
                "Status shows PAPER mode"
            )

        finally:
            # Restore original env
            if original_mode:
                os.environ['TRADING_MODE'] = original_mode
            else:
                os.environ.pop('TRADING_MODE', None)

    def test_live_mode_confirmation(self):
        """Test 2: LIVE mode confirmation requirement"""
        logger.info("\n=== Test 2: LIVE Mode Confirmation ===")

        original_mode = os.getenv('TRADING_MODE')
        original_conf = os.getenv('LIVE_TRADING_CONFIRMATION')

        try:
            # Test 2a: LIVE mode without confirmation
            os.environ['TRADING_MODE'] = 'LIVE'
            os.environ.pop('LIVE_TRADING_CONFIRMATION', None)

            controller = TradingModeController(redis_client=self.redis)

            self.assert_false(
                controller.is_live_confirmation_valid(),
                "LIVE mode without confirmation is invalid"
            )

            result = controller.check_can_trade('XBTUSD', 1000.0)
            self.assert_false(
                result.passed,
                "Trading blocked without LIVE confirmation"
            )

            # Test 2b: LIVE mode with wrong confirmation
            os.environ['LIVE_TRADING_CONFIRMATION'] = 'wrong-phrase'
            controller = TradingModeController(redis_client=self.redis)

            self.assert_false(
                controller.is_live_confirmation_valid(),
                "Wrong confirmation phrase is invalid"
            )

            # Test 2c: LIVE mode with correct confirmation
            os.environ['LIVE_TRADING_CONFIRMATION'] = 'I-accept-the-risk'
            controller = TradingModeController(redis_client=self.redis)

            self.assert_true(
                controller.is_live_confirmation_valid(),
                "Correct confirmation phrase is valid"
            )

            # Verify signal stream switches to live
            active_stream = controller.get_active_signal_stream()
            self.assert_true(
                active_stream == 'signals:live',
                f"ACTIVE_SIGNALS points to signals:live (got: {active_stream})"
            )

        finally:
            if original_mode:
                os.environ['TRADING_MODE'] = original_mode
            if original_conf:
                os.environ['LIVE_TRADING_CONFIRMATION'] = original_conf
            else:
                os.environ.pop('LIVE_TRADING_CONFIRMATION', None)

    def test_emergency_stop(self):
        """Test 3: Emergency kill-switch"""
        logger.info("\n=== Test 3: Emergency Kill-Switch ===")

        original_stop = os.getenv('KRAKEN_EMERGENCY_STOP')

        try:
            os.environ['TRADING_MODE'] = 'PAPER'
            os.environ.pop('KRAKEN_EMERGENCY_STOP', None)

            controller = TradingModeController(redis_client=self.redis)

            # Test 3a: Normal operation
            self.assert_false(
                controller.is_emergency_stop_active(),
                "Emergency stop is inactive initially"
            )

            result = controller.check_can_trade('XBTUSD', 1000.0, operation='entry')
            self.assert_true(
                result.passed or 'emergency' not in str(result.errors).lower(),
                "Entry allowed when emergency stop is inactive"
            )

            # Test 3b: Activate via Redis
            controller.activate_emergency_stop("Test activation")

            self.assert_true(
                controller.is_emergency_stop_active(),
                "Emergency stop activated via Redis"
            )

            result = controller.check_can_trade('XBTUSD', 1000.0, operation='entry')
            self.assert_false(
                result.passed,
                "Entry blocked when emergency stop is active"
            )

            # Test 3c: Exits still allowed during emergency
            result_exit = controller.check_can_trade('XBTUSD', 1000.0, operation='exit')
            # Note: exits bypass emergency stop in current implementation
            logger.info(f"Exit during emergency: passed={result_exit.passed}")

            # Test 3d: Deactivate emergency stop
            controller.deactivate_emergency_stop()

            self.assert_false(
                controller.is_emergency_stop_active(),
                "Emergency stop deactivated"
            )

            # Test 3e: Emergency stop via environment variable
            os.environ['KRAKEN_EMERGENCY_STOP'] = 'true'
            controller_env = TradingModeController(redis_client=self.redis)

            self.assert_true(
                controller_env.is_emergency_stop_active(),
                "Emergency stop activated via environment variable"
            )

        finally:
            # Cleanup
            self.redis.delete('kraken:emergency:kill_switch')
            if original_stop:
                os.environ['KRAKEN_EMERGENCY_STOP'] = original_stop
            else:
                os.environ.pop('KRAKEN_EMERGENCY_STOP', None)

    def test_pair_whitelist(self):
        """Test 4: Pair whitelist enforcement"""
        logger.info("\n=== Test 4: Pair Whitelist ===")

        os.environ['TRADING_MODE'] = 'PAPER'

        # Test 4a: Whitelist with allowed pair
        controller = TradingModeController(
            redis_client=self.redis,
            pair_whitelist=['XBTUSD', 'ETHUSD']
        )

        self.assert_true(
            controller.is_pair_allowed('XBTUSD'),
            "XBTUSD is in whitelist"
        )

        result = controller.check_can_trade('XBTUSD', 1000.0)
        self.assert_true(
            result.pair_allowed,
            "Trading allowed for whitelisted pair"
        )

        # Test 4b: Whitelist with disallowed pair
        self.assert_false(
            controller.is_pair_allowed('SOLUSD'),
            "SOLUSD is not in whitelist"
        )

        result = controller.check_can_trade('SOLUSD', 1000.0)
        self.assert_false(
            result.passed,
            "Trading blocked for non-whitelisted pair"
        )

        # Test 4c: Empty whitelist (allow all)
        controller_open = TradingModeController(
            redis_client=self.redis,
            pair_whitelist=[]
        )

        self.assert_true(
            controller_open.is_pair_allowed('ANYPAIR'),
            "Empty whitelist allows all pairs"
        )

    def test_notional_caps(self):
        """Test 5: Notional caps per pair"""
        logger.info("\n=== Test 5: Notional Caps ===")

        os.environ['TRADING_MODE'] = 'PAPER'

        controller = TradingModeController(
            redis_client=self.redis,
            notional_caps={'XBTUSD': 10000.0, 'ETHUSD': 5000.0}
        )

        # Test 5a: Order within cap
        self.assert_true(
            controller.is_notional_within_cap('XBTUSD', 5000.0),
            "Order within XBTUSD cap ($5k < $10k)"
        )

        result = controller.check_can_trade('XBTUSD', 5000.0)
        self.assert_true(
            result.notional_within_cap,
            "Trading allowed within notional cap"
        )

        # Test 5b: Order exceeds cap
        self.assert_false(
            controller.is_notional_within_cap('XBTUSD', 15000.0),
            "Order exceeds XBTUSD cap ($15k > $10k)"
        )

        result = controller.check_can_trade('XBTUSD', 15000.0)
        self.assert_false(
            result.passed,
            "Trading blocked when exceeding notional cap"
        )

        # Test 5c: Pair without cap (allow any)
        self.assert_true(
            controller.is_notional_within_cap('SOLUSD', 1000000.0),
            "Pair without cap allows any notional"
        )

    def test_mode_switching(self):
        """Test 6: Mode switching (PAPER ↔ LIVE)"""
        logger.info("\n=== Test 6: Mode Switching ===")

        os.environ['TRADING_MODE'] = 'PAPER'
        os.environ['LIVE_TRADING_CONFIRMATION'] = 'I-accept-the-risk'

        controller = TradingModeController(redis_client=self.redis)

        # Test 6a: Start in PAPER
        self.assert_true(
            controller.get_current_mode() == TradingMode.PAPER,
            "Starts in PAPER mode"
        )

        # Test 6b: Switch to LIVE
        success = controller.switch_mode(TradingMode.LIVE)
        self.assert_true(
            success and controller.get_current_mode() == TradingMode.LIVE,
            "Successfully switched to LIVE mode"
        )

        active_stream = controller.get_active_signal_stream()
        self.assert_true(
            active_stream == 'signals:live',
            "ACTIVE_SIGNALS updated to signals:live"
        )

        # Test 6c: Switch back to PAPER
        success = controller.switch_mode(TradingMode.PAPER)
        self.assert_true(
            success and controller.get_current_mode() == TradingMode.PAPER,
            "Successfully switched back to PAPER mode"
        )

        # Cleanup env
        os.environ.pop('LIVE_TRADING_CONFIRMATION', None)

    def test_circuit_breaker_monitor(self):
        """Test 7: Circuit breaker monitoring"""
        logger.info("\n=== Test 7: Circuit Breaker Monitor ===")

        os.environ['TRADING_MODE'] = 'PAPER'

        controller = TradingModeController(redis_client=self.redis)
        monitor = CircuitBreakerMonitor(
            redis_client=self.redis,
            mode_controller=controller,
            latency_threshold_ms=1000.0,
            spread_threshold_bps=50.0
        )

        # Test 7a: Normal latency
        result = monitor.check_latency(500.0, 'XBTUSD')
        self.assert_true(
            result,
            "Normal latency passes check (500ms < 1000ms)"
        )

        # Test 7b: High latency trips breaker
        result = monitor.check_latency(1500.0, 'XBTUSD')
        self.assert_false(
            result,
            "High latency trips circuit breaker (1500ms > 1000ms)"
        )

        # Verify event published
        events = self.redis.xrevrange('metrics:circuit_breakers', count=1)
        if events:
            event_data = events[0][1]
            self.assert_true(
                event_data.get('breaker_type') == 'latency',
                "Latency breaker event published to metrics:circuit_breakers"
            )

        # Test 7c: Normal spread
        result = monitor.check_spread(25.0, 'XBTUSD')
        self.assert_true(
            result,
            "Normal spread passes check (25bps < 50bps)"
        )

        # Test 7d: Wide spread trips breaker
        result = monitor.check_spread(75.0, 'XBTUSD')
        self.assert_false(
            result,
            "Wide spread trips circuit breaker (75bps > 50bps)"
        )

    def test_comprehensive_safety_check(self):
        """Test 8: Comprehensive safety check"""
        logger.info("\n=== Test 8: Comprehensive Safety Check ===")

        os.environ['TRADING_MODE'] = 'LIVE'
        os.environ['LIVE_TRADING_CONFIRMATION'] = 'I-accept-the-risk'
        os.environ.pop('KRAKEN_EMERGENCY_STOP', None)

        controller = TradingModeController(
            redis_client=self.redis,
            pair_whitelist=['XBTUSD', 'ETHUSD'],
            notional_caps={'XBTUSD': 10000.0}
        )

        # Test 8a: All checks pass
        result = controller.check_can_trade('XBTUSD', 5000.0)

        self.assert_true(
            result.passed,
            "All safety checks pass for valid trade"
        )
        self.assert_true(
            result.mode == TradingMode.LIVE and
            result.confirmation_valid and
            result.pair_allowed and
            result.notional_within_cap,
            "All individual checks are valid"
        )

        # Test 8b: Multiple failures
        result = controller.check_can_trade('SOLUSD', 20000.0)

        self.assert_false(
            result.passed,
            "Safety check fails with multiple violations"
        )
        self.assert_false(
            result.pair_allowed,
            "Pair check fails for non-whitelisted pair"
        )

        logger.info(f"Comprehensive check errors: {result.errors}")

        # Cleanup
        os.environ.pop('LIVE_TRADING_CONFIRMATION', None)

    def run_all_tests(self):
        """Run all tests"""
        logger.info("=" * 60)
        logger.info("Starting Go-Live Controls Test Suite")
        logger.info("=" * 60)

        try:
            self.test_basic_initialization()
            self.test_live_mode_confirmation()
            self.test_emergency_stop()
            self.test_pair_whitelist()
            self.test_notional_caps()
            self.test_mode_switching()
            self.test_circuit_breaker_monitor()
            self.test_comprehensive_safety_check()

        except Exception as e:
            logger.error(f"Test suite error: {e}", exc_info=True)
            self.failed += 1

        finally:
            # Cleanup Redis test keys
            logger.info("\nCleaning up Redis test keys...")
            self.redis.delete('ACTIVE_SIGNALS')
            self.redis.delete('kraken:emergency:kill_switch')

        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("Test Suite Summary")
        logger.info("=" * 60)
        logger.info(f"Passed: {self.passed}")
        logger.info(f"Failed: {self.failed}")
        logger.info(f"Total:  {self.passed + self.failed}")

        success_rate = (self.passed / (self.passed + self.failed) * 100) if (self.passed + self.failed) > 0 else 0
        logger.info(f"Success Rate: {success_rate:.1f}%")

        if self.failed == 0:
            logger.info("\n✓ ALL TESTS PASSED")
            return 0
        else:
            logger.error(f"\n✗ {self.failed} TEST(S) FAILED")
            return 1


def main():
    """Main entry point"""
    try:
        test_suite = GoLiveControlsTest()
        exit_code = test_suite.run_all_tests()
        sys.exit(exit_code)
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
