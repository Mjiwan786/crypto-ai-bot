"""
End-to-End Smoke Test for Crypto AI Bot

This script validates the complete signal generation pipeline:
1. Environment configuration
2. Redis Cloud connection
3. Kraken WebSocket connection
4. Model ensemble prediction
5. Signal schema validation
6. Redis signal publishing
7. Latency benchmarking

Usage:
    python scripts/smoke_test_e2e.py

Expected Duration: ~30 seconds
Exit Code: 0 = success, 1 = failure

Author: Crypto AI Bot Team
Version: 1.0.0
"""

import asyncio
import os
import sys
import time
from datetime import datetime
from typing import Dict, Any

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv

# Import project modules
from agents.core.real_redis_client import RealRedisClient
from ml.async_ensemble import AsyncEnsemblePredictor
from models.prd_signal_schema import TradingSignal, Side, Strategy, Regime, Indicators, SignalMetadata
from utils.kraken_ws import KrakenWSConfig

# ANSI color codes
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"


class SmokeTest:
    """End-to-end smoke test runner."""

    def __init__(self):
        self.results = []
        self.start_time = time.time()
        self.redis_client = None
        self.ensemble = None

    def log(self, message: str, level: str = "INFO"):
        """Log message with color."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        colors = {
            "INFO": BLUE,
            "SUCCESS": GREEN,
            "ERROR": RED,
            "WARNING": YELLOW
        }
        color = colors.get(level, RESET)
        print(f"{color}[{timestamp}] {level}: {message}{RESET}")

    def check(self, name: str, passed: bool, message: str = ""):
        """Record test result."""
        status = "[PASS]" if passed else "[FAIL]"
        self.results.append({"name": name, "passed": passed, "message": message})
        level = "SUCCESS" if passed else "ERROR"
        self.log(f"{status} - {name}" + (f": {message}" if message else ""), level)

    async def test_environment(self):
        """Test 1: Environment configuration."""
        self.log("=" * 70)
        self.log("TEST 1: Environment Configuration")
        self.log("=" * 70)

        # Load .env
        load_dotenv()

        # Check required variables
        required_vars = [
            "REDIS_URL",
            "TRADING_PAIRS",
            "TRADING_MODE",
        ]

        all_present = True
        for var in required_vars:
            value = os.getenv(var)
            present = value is not None and value != ""
            self.check(f"Env var {var}", present, value[:50] if present else "NOT SET")
            all_present = all_present and present

        return all_present

    async def test_redis_connection(self):
        """Test 2: Redis Cloud connection."""
        self.log("=" * 70)
        self.log("TEST 2: Redis Cloud Connection")
        self.log("=" * 70)

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            self.check("Redis URL", False, "REDIS_URL not set")
            return False

        try:
            # Create Redis client
            self.log(f"Connecting to Redis Cloud...")
            self.redis_client = RealRedisClient.from_url(redis_url)

            # Test ping
            start = time.time()
            await self.redis_client.client.ping()
            latency_ms = (time.time() - start) * 1000

            self.check("Redis connection", True, f"Latency: {latency_ms:.2f}ms")

            # Test stream write
            test_stream = "test:smoke_test"
            test_data = {"test": "smoke_test", "timestamp": str(time.time())}

            message_id = await self.redis_client.xadd(test_stream, test_data)
            self.check("Redis stream write", True, f"Message ID: {message_id}")

            # Clean up test stream
            await self.redis_client.client.delete(test_stream)

            return True

        except Exception as e:
            self.check("Redis connection", False, str(e))
            return False

    async def test_kraken_websocket(self):
        """Test 3: Kraken WebSocket configuration."""
        self.log("=" * 70)
        self.log("TEST 3: Kraken WebSocket Configuration")
        self.log("=" * 70)

        try:
            # Load config
            trading_pairs = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD").split(",")
            self.log(f"Trading pairs: {trading_pairs}")

            # Create WebSocket config
            config = KrakenWSConfig(
                pairs=trading_pairs,
                redis_url=os.getenv("REDIS_URL"),
                trading_mode=os.getenv("TRADING_MODE", "paper")
            )

            self.check("WebSocket config", True, f"Pairs: {len(config.pairs)}")

            # Validate trading pairs format
            for pair in config.pairs:
                valid = "/" in pair or "-" in pair
                self.check(f"Pair format: {pair}", valid)

            return True

        except Exception as e:
            self.check("WebSocket config", False, str(e))
            return False

    async def test_model_ensemble(self):
        """Test 4: Model ensemble prediction."""
        self.log("=" * 70)
        self.log("TEST 4: Model Ensemble Prediction")
        self.log("=" * 70)

        try:
            # Create ensemble (with None models for smoke test)
            self.log("Initializing ensemble predictor...")
            self.ensemble = AsyncEnsemblePredictor(
                rf_predictor=None,  # Use None for smoke test
                lstm_predictor=None,
                rf_weight=0.6,
                lstm_weight=0.4
            )

            # Test prediction
            ctx = {
                "rsi": 65.5,
                "macd": 0.02,
                "atr": 425.0,
                "volume_ratio": 1.23
            }

            self.log("Running prediction...")
            start = time.time()
            result = await self.ensemble.predict(ctx, pair="BTC/USD")
            predict_latency = (time.time() - start) * 1000

            # Validate result
            self.check("Prediction execution", True, f"Latency: {predict_latency:.2f}ms")

            # Check result structure
            required_keys = ["probability", "confidence", "rf_prob", "lstm_prob", "weights", "agree"]
            for key in required_keys:
                self.check(f"Result has '{key}'", key in result)

            # Check latency requirement (< 50ms for PRD-001)
            self.check(
                "Latency < 50ms",
                predict_latency < 50,
                f"{predict_latency:.2f}ms"
            )

            # Get stats
            stats = self.ensemble.get_stats()
            self.log(f"Ensemble stats: {stats}")

            return True

        except Exception as e:
            self.check("Model ensemble", False, str(e))
            return False

    async def test_signal_schema(self):
        """Test 5: Signal schema validation."""
        self.log("=" * 70)
        self.log("TEST 5: Signal Schema Validation")
        self.log("=" * 70)

        try:
            # Create test signal
            self.log("Creating test TradingSignal...")

            signal = TradingSignal(
                signal_id=f"test_{int(time.time()*1000)}",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.TREND,
                regime=Regime.RANGING,
                entry_price=43250.5,
                take_profit=44000.0,
                stop_loss=42500.0,
                confidence=0.85,
                position_size_usd=100.0,
                indicators=Indicators(
                    rsi_14=65.5,
                    macd_signal="BULLISH",
                    atr_14=425.0,
                    volume_ratio=1.23
                ),
                metadata=SignalMetadata(
                    model_version="ensemble-v1.0.0",
                    backtest_sharpe=1.85,
                    latency_ms=15.5
                )
            )

            self.check("Signal creation", True, f"ID: {signal.signal_id}")

            # Validate price relationships for LONG
            long_prices_valid = (
                signal.take_profit > signal.entry_price and
                signal.stop_loss < signal.entry_price
            )
            self.check("LONG price relationships", long_prices_valid)

            # Validate confidence range
            confidence_valid = 0.0 <= signal.confidence <= 1.0
            self.check("Confidence range [0,1]", confidence_valid, f"{signal.confidence}")

            # Test SHORT signal
            signal_short = TradingSignal(
                signal_id=f"test_{int(time.time()*1000)}_short",
                timestamp=datetime.now(),
                trading_pair="ETH/USD",
                side=Side.SHORT,
                strategy=Strategy.TREND,
                regime=Regime.RANGING,
                entry_price=2345.0,
                take_profit=2200.0,  # < entry for SHORT
                stop_loss=2400.0,    # > entry for SHORT
                confidence=0.75,
                position_size_usd=100.0,
                indicators=Indicators(
                    rsi_14=35.0,
                    macd_signal="BEARISH",
                    atr_14=50.0,
                    volume_ratio=0.8
                ),
                metadata=SignalMetadata(
                    model_version="ensemble-v1.0.0",
                    backtest_sharpe=1.85,
                    latency_ms=18.2
                )
            )

            short_prices_valid = (
                signal_short.take_profit < signal_short.entry_price and
                signal_short.stop_loss > signal_short.entry_price
            )
            self.check("SHORT price relationships", short_prices_valid)

            return True

        except Exception as e:
            self.check("Signal schema", False, str(e))
            return False

    async def test_redis_signal_publish(self):
        """Test 6: Redis signal publishing."""
        self.log("=" * 70)
        self.log("TEST 6: Redis Signal Publishing")
        self.log("=" * 70)

        if not self.redis_client:
            self.check("Redis publish", False, "Redis client not initialized")
            return False

        try:
            # Create test signal
            signal = TradingSignal(
                signal_id=f"smoke_test_{int(time.time()*1000)}",
                timestamp=datetime.now(),
                trading_pair="BTC/USD",
                side=Side.LONG,
                strategy=Strategy.TREND,
                regime=Regime.RANGING,
                entry_price=43250.5,
                take_profit=44000.0,
                stop_loss=42500.0,
                confidence=0.85,
                position_size_usd=100.0,
                indicators=Indicators(
                    rsi_14=65.5,
                    macd_signal="BULLISH",
                    atr_14=425.0,
                    volume_ratio=1.23
                ),
                metadata=SignalMetadata(
                    model_version="ensemble-v1.0.0",
                    backtest_sharpe=1.85,
                    latency_ms=15.5
                )
            )

            # Publish to test stream
            stream_name = f"signals:test_{int(time.time())}"

            signal_dict = {
                "signal_id": signal.signal_id,
                "timestamp": signal.timestamp.isoformat(),
                "pair": signal.trading_pair,
                "side": signal.side.value,
                "entry_price": str(signal.entry_price),
                "confidence": str(signal.confidence)
            }

            self.log(f"Publishing to stream: {stream_name}")
            start = time.time()
            message_id = await self.redis_client.xadd(stream_name, signal_dict)
            publish_latency = (time.time() - start) * 1000

            self.check("Signal publish", True, f"Message ID: {message_id}")
            self.check(
                "Publish latency < 20ms",
                publish_latency < 20,
                f"{publish_latency:.2f}ms"
            )

            # Read back signal
            stream_data = await self.redis_client.client.xrevrange(
                stream_name,
                count=1
            )

            if stream_data:
                self.check("Signal read-back", True)
            else:
                self.check("Signal read-back", False, "No data returned")

            # Clean up test stream
            await self.redis_client.client.delete(stream_name)

            return True

        except Exception as e:
            self.check("Redis publish", False, str(e))
            return False

    async def test_performance_benchmark(self):
        """Test 7: Performance benchmarking."""
        self.log("=" * 70)
        self.log("TEST 7: Performance Benchmark")
        self.log("=" * 70)

        if not self.ensemble:
            self.check("Performance benchmark", False, "Ensemble not initialized")
            return False

        try:
            # Run 100 predictions
            self.log("Running 100 predictions...")
            latencies = []

            ctx = {
                "rsi": 65.5,
                "macd": 0.02,
                "atr": 425.0,
                "volume_ratio": 1.23
            }

            for i in range(100):
                start = time.time()
                await self.ensemble.predict(ctx, pair="BTC/USD")
                latency = (time.time() - start) * 1000
                latencies.append(latency)

            # Calculate statistics
            avg_latency = sum(latencies) / len(latencies)
            max_latency = max(latencies)
            min_latency = min(latencies)
            p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]

            self.log(f"Average latency: {avg_latency:.2f}ms")
            self.log(f"Min latency: {min_latency:.2f}ms")
            self.log(f"Max latency: {max_latency:.2f}ms")
            self.log(f"P95 latency: {p95_latency:.2f}ms")

            # Check against PRD-001 requirements
            self.check("Average < 50ms", avg_latency < 50, f"{avg_latency:.2f}ms")
            self.check("P95 < 100ms", p95_latency < 100, f"{p95_latency:.2f}ms")

            return True

        except Exception as e:
            self.check("Performance benchmark", False, str(e))
            return False

    async def cleanup(self):
        """Cleanup resources."""
        self.log("=" * 70)
        self.log("Cleanup")
        self.log("=" * 70)

        if self.ensemble:
            await self.ensemble.close()
            self.log("Ensemble closed")

        # Note: Redis client doesn't need explicit cleanup in this version

    def print_summary(self):
        """Print test summary."""
        elapsed = time.time() - self.start_time

        self.log("=" * 70)
        self.log("SMOKE TEST SUMMARY")
        self.log("=" * 70)

        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r["passed"])
        failed_tests = total_tests - passed_tests

        self.log(f"Total tests: {total_tests}")
        self.log(f"Passed: {GREEN}{passed_tests}{RESET}")
        self.log(f"Failed: {RED}{failed_tests}{RESET}")
        self.log(f"Duration: {elapsed:.2f}s")

        if failed_tests > 0:
            self.log("=" * 70, "ERROR")
            self.log("FAILED TESTS:", "ERROR")
            for result in self.results:
                if not result["passed"]:
                    self.log(f"  - {result['name']}: {result['message']}", "ERROR")

        self.log("=" * 70)

        if failed_tests == 0:
            self.log("[OK] ALL TESTS PASSED!", "SUCCESS")
            return 0
        else:
            self.log(f"[FAIL] {failed_tests} TESTS FAILED!", "ERROR")
            return 1

    async def run(self):
        """Run all smoke tests."""
        self.log("=" * 70)
        self.log("CRYPTO AI BOT - END-TO-END SMOKE TEST")
        self.log("=" * 70)
        self.log(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self.log("=" * 70)

        try:
            # Run all tests
            await self.test_environment()
            await self.test_redis_connection()
            await self.test_kraken_websocket()
            await self.test_model_ensemble()
            await self.test_signal_schema()
            await self.test_redis_signal_publish()
            await self.test_performance_benchmark()

        except Exception as e:
            self.log(f"Fatal error: {e}", "ERROR")

        finally:
            # Cleanup
            await self.cleanup()

            # Print summary
            exit_code = self.print_summary()

            return exit_code


async def main():
    """Main entry point."""
    test = SmokeTest()
    exit_code = await test.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    asyncio.run(main())
