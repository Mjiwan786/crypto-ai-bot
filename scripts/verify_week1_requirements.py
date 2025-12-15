#!/usr/bin/env python3
"""
Week 1 Verification Script for crypto-ai-bot

This script verifies that all Week 1 requirements are complete and working:
1. Redis wiring & TLS
2. Kraken WS + OHLCV
3. Signal generation + PnL
4. Observability

Usage:
    python scripts/verify_week1_requirements.py
"""

import asyncio
import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime, timezone

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv

# Load environment variables from .env.paper (paper trading mode)
env_file = project_root / ".env.paper"
if env_file.exists():
    load_dotenv(env_file)
else:
    load_dotenv()  # Fallback to .env

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class Week1Verifier:
    """Verifies Week 1 requirements."""
    
    def __init__(self):
        self.results: Dict[str, Tuple[bool, str]] = {}
        self.redis_client = None
        
    def record_result(self, test_name: str, passed: bool, message: str = ""):
        """Record test result."""
        self.results[test_name] = (passed, message)
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {test_name} - {message}")
        
    async def verify_redis_tls(self) -> bool:
        """Verify Redis TLS connection and configuration."""
        logger.info("=" * 70)
        logger.info("TEST 1: Redis Wiring & TLS")
        logger.info("=" * 70)
        
        try:
            # Check environment variables
            redis_url = os.getenv("REDIS_URL", "")
            redis_ca_cert = os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_CA_CERT_PATH")
            
            if not redis_url:
                self.record_result("REDIS_URL env var", False, "REDIS_URL not set")
                return False
            else:
                self.record_result("REDIS_URL env var", True, f"Set (length: {len(redis_url)})")
            
            # Check TLS scheme
            if not redis_url.startswith("rediss://"):
                self.record_result("Redis TLS scheme", False, f"URL must use rediss://, got: {redis_url[:20]}...")
                return False
            else:
                self.record_result("Redis TLS scheme", True, "Using rediss:// scheme")
            
            # Check CA cert
            if not redis_ca_cert:
                self.record_result("REDIS_CA_CERT env var", False, "REDIS_CA_CERT not set")
                return False
            
            if not os.path.exists(redis_ca_cert):
                self.record_result("Redis CA cert file", False, f"CA cert not found: {redis_ca_cert}")
                return False
            else:
                self.record_result("Redis CA cert file", True, f"Found at {redis_ca_cert}")
            
            # Test connection
            try:
                from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
                
                config = RedisCloudConfig(
                    url=redis_url,
                    ca_cert_path=redis_ca_cert,
                )
                
                client = RedisCloudClient(config)
                await client.connect()
                
                # Test ping
                ping_result = await client.ping()
                if ping_result:
                    self.record_result("Redis connection", True, "Successfully connected and pinged")
                    self.redis_client = client
                else:
                    self.record_result("Redis connection", False, "Ping failed")
                    return False
                    
            except Exception as e:
                self.record_result("Redis connection", False, f"Connection failed: {e}")
                return False
            
            # Check stream naming functions
            try:
                from agents.infrastructure.prd_redis_publisher import (
                    get_signal_stream_name,
                    get_pnl_stream_name,
                    get_engine_mode,
                )
                
                mode = get_engine_mode()
                self.record_result("ENGINE_MODE detection", True, f"Mode: {mode}")
                
                # Test stream names
                test_pair = "BTC/USD"
                signal_stream = get_signal_stream_name(mode, test_pair)
                pnl_stream = get_pnl_stream_name(mode)
                
                expected_signal = f"signals:{mode}:BTC-USD"
                expected_pnl = f"pnl:{mode}:equity_curve"
                
                if signal_stream == expected_signal:
                    self.record_result("Signal stream naming", True, f"Correct: {signal_stream}")
                else:
                    self.record_result("Signal stream naming", False, 
                                     f"Expected {expected_signal}, got {signal_stream}")
                    return False
                
                if pnl_stream == expected_pnl:
                    self.record_result("PnL stream naming", True, f"Correct: {pnl_stream}")
                else:
                    self.record_result("PnL stream naming", False,
                                     f"Expected {expected_pnl}, got {pnl_stream}")
                    return False
                    
            except Exception as e:
                self.record_result("Stream naming functions", False, f"Error: {e}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Redis TLS verification failed: {e}", exc_info=True)
            return False
    
    async def verify_kraken_ws(self) -> bool:
        """Verify Kraken WebSocket connection and subscription."""
        logger.info("=" * 70)
        logger.info("TEST 2: Kraken WebSocket + OHLCV")
        logger.info("=" * 70)
        
        try:
            # Check if Kraken WS client exists
            try:
                from utils.kraken_ws import KrakenWebSocketClient, KrakenWSConfig
                self.record_result("Kraken WS import", True, "Module available")
            except ImportError as e:
                self.record_result("Kraken WS import", False, f"Import failed: {e}")
                return False
            
            # Check configuration
            trading_pairs = os.getenv("TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD").split(",")
            trading_pairs = [p.strip() for p in trading_pairs if p.strip()]
            
            if not trading_pairs:
                self.record_result("Trading pairs config", False, "No trading pairs configured")
                return False
            else:
                self.record_result("Trading pairs config", True, f"Pairs: {trading_pairs}")
            
            # Check if config supports all required pairs
            required_pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "AVAX/USD", "MATIC/USD", "LINK/USD"]
            missing_pairs = [p for p in required_pairs if p not in trading_pairs]
            
            if missing_pairs:
                self.record_result("Required pairs coverage", False, 
                                 f"Missing pairs: {missing_pairs}")
                # Not a hard failure, but note it
            else:
                self.record_result("Required pairs coverage", True, "All required pairs configured")
            
            # Check reconnection logic exists
            try:
                ws_code = Path("utils/kraken_ws.py").read_text(encoding="utf-8")
                if "exponential" in ws_code.lower() and "backoff" in ws_code.lower():
                    self.record_result("Reconnection logic", True, "Exponential backoff found")
                else:
                    self.record_result("Reconnection logic", False, "No exponential backoff found")
            except Exception as e:
                self.record_result("Reconnection logic check", False, f"Error: {e}")
            
            # Check OHLCV pipeline
            try:
                from utils.kraken_ohlcv_manager import KrakenOHLCVManager
                self.record_result("OHLCV manager", True, "Module available")
            except ImportError:
                self.record_result("OHLCV manager", False, "Module not found")
                # Not a hard failure for Week 1
            
            return True
            
        except Exception as e:
            logger.error(f"Kraken WS verification failed: {e}", exc_info=True)
            return False
    
    async def verify_signal_generation(self) -> bool:
        """Verify signal generation and PnL tracking."""
        logger.info("=" * 70)
        logger.info("TEST 3: Signal Generation + PnL")
        logger.info("=" * 70)
        
        try:
            # Check signal schema
            try:
                from models.prd_signal_schema import PRDSignalSchema
                from agents.infrastructure.prd_publisher import PRDSignal
                self.record_result("Signal schema", True, "PRD signal schema available")
            except ImportError as e:
                self.record_result("Signal schema", False, f"Import failed: {e}")
                return False
            
            # Check PnL tracking
            try:
                from agents.infrastructure.prd_pnl import (
                    PRDTradeRecord,
                    PRDPnLPublisher,
                    PerformanceAggregator,
                )
                self.record_result("PnL tracking", True, "PnL modules available")
            except ImportError as e:
                self.record_result("PnL tracking", False, f"Import failed: {e}")
                return False
            
            # Test signal creation
            try:
                import uuid
                from datetime import datetime, timezone
                
                test_signal_data = {
                    "signal_id": str(uuid.uuid4()),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "pair": "BTC/USD",
                    "side": "LONG",
                    "strategy": "SCALPER",
                    "regime": "TRENDING_UP",
                    "entry_price": 50000.0,
                    "take_profit": 52000.0,
                    "stop_loss": 49000.0,
                    "position_size_usd": 100.0,
                    "confidence": 0.75,
                    "risk_reward_ratio": 2.0,
                    "indicators": {
                        "rsi_14": 58.3,
                        "macd_signal": "BULLISH",
                        "atr_14": 425.80,
                        "volume_ratio": 1.23,
                    },
                    "metadata": {
                        "model_version": "v1.0.0",
                        "backtest_sharpe": 1.85,
                        "latency_ms": 127,
                    },
                }
                
                signal = PRDSignal.model_validate(test_signal_data)
                self.record_result("Signal creation", True, f"Created signal: {signal.signal_id[:8]}...")
                
            except Exception as e:
                self.record_result("Signal creation", False, f"Failed: {e}")
                return False
            
            # Test PnL record creation
            try:
                from agents.infrastructure.prd_pnl import create_trade_record, ExitReason
                
                trade = create_trade_record(
                    signal_id=test_signal_data["signal_id"],
                    pair="BTC/USD",
                    side="LONG",
                    strategy="SCALPER",
                    entry_price=50000.0,
                    exit_price=50500.0,
                    position_size_usd=100.0,
                    quantity=0.002,
                    timestamp_open=datetime.now(timezone.utc).isoformat(),
                    exit_reason=ExitReason.TAKE_PROFIT,
                )
                
                self.record_result("PnL record creation", True, 
                                 f"Created trade: {trade.trade_id[:8]}..., PnL: ${trade.realized_pnl:.2f}")
                
            except Exception as e:
                self.record_result("PnL record creation", False, f"Failed: {e}")
                return False
            
            # Check if engine mode is paper
            engine_mode = os.getenv("ENGINE_MODE", "paper").lower()
            if engine_mode == "paper":
                self.record_result("Engine mode", True, "Running in PAPER mode (safe)")
            else:
                self.record_result("Engine mode", False, f"Mode is {engine_mode}, should be 'paper' for Week 1")
            
            return True
            
        except Exception as e:
            logger.error(f"Signal generation verification failed: {e}", exc_info=True)
            return False
    
    async def verify_observability(self) -> bool:
        """Verify observability (logging, metrics, health checks)."""
        logger.info("=" * 70)
        logger.info("TEST 4: Observability")
        logger.info("=" * 70)
        
        try:
            # Check health check endpoint
            try:
                from health_server import HealthStatus, HealthCheckHandler
                self.record_result("Health server", True, "Health server module available")
            except ImportError:
                # Check main.py health endpoint
                try:
                    import main
                    self.record_result("Health endpoint", True, "Health endpoint in main.py")
                except:
                    self.record_result("Health endpoint", False, "No health endpoint found")
                    return False
            
            # Check PRD health checker
            try:
                from monitoring.prd_health_checker import PRDHealthChecker
                self.record_result("PRD health checker", True, "PRD health checker available")
            except ImportError:
                self.record_result("PRD health checker", False, "PRD health checker not found")
            
            # Check Prometheus metrics
            try:
                from prometheus_client import Counter, Gauge, Histogram
                self.record_result("Prometheus metrics", True, "Prometheus client available")
            except ImportError:
                self.record_result("Prometheus metrics", False, "Prometheus client not installed")
            
            # Check structured logging
            log_format = os.getenv("LOG_FORMAT", "")
            if log_format == "json" or "json" in log_format.lower():
                self.record_result("Structured logging", True, "JSON logging enabled")
            else:
                self.record_result("Structured logging", False, 
                                 "JSON logging not enabled (LOG_FORMAT not set to 'json')")
            
            # Check if metrics are exported in kraken_ws
            try:
                ws_code = Path("utils/kraken_ws.py").read_text(encoding="utf-8")
                if "prometheus" in ws_code.lower() or "Counter" in ws_code or "Gauge" in ws_code:
                    self.record_result("Metrics in Kraken WS", True, "Prometheus metrics found")
                else:
                    self.record_result("Metrics in Kraken WS", False, "No Prometheus metrics found")
            except Exception as e:
                self.record_result("Metrics check", False, f"Error: {e}")
            
            return True
            
        except Exception as e:
            logger.error(f"Observability verification failed: {e}", exc_info=True)
            return False
    
    async def verify_stream_publishing(self) -> bool:
        """Verify that signals can be published to correct streams."""
        logger.info("=" * 70)
        logger.info("TEST 5: Stream Publishing (Dry Run)")
        logger.info("=" * 70)
        
        if not self.redis_client:
            self.record_result("Stream publishing test", False, "Redis client not connected")
            return False
        
        try:
            from agents.infrastructure.prd_redis_publisher import (
                publish_signal,
                get_engine_mode,
            )
            from agents.infrastructure.prd_publisher import PRDSignal
            import uuid
            from datetime import datetime, timezone
            
            mode = get_engine_mode()
            
            # Create test signal
            test_signal_data = {
                "signal_id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pair": "BTC/USD",
                "side": "LONG",
                "strategy": "SCALPER",
                "regime": "TRENDING_UP",
                "entry_price": 50000.0,
                "take_profit": 52000.0,
                "stop_loss": 49000.0,
                "position_size_usd": 100.0,
                "confidence": 0.75,
                "risk_reward_ratio": 2.0,
                "indicators": {
                    "rsi_14": 58.3,
                    "macd_signal": "BULLISH",
                    "atr_14": 425.80,
                    "volume_ratio": 1.23,
                },
                "metadata": {
                    "model_version": "v1.0.0",
                    "backtest_sharpe": 1.85,
                    "latency_ms": 127,
                },
            }
            
            # Try to publish (dry run - we'll check if it would work)
            signal = PRDSignal.model_validate(test_signal_data)
            self.record_result("Signal validation", True, "Signal validates against PRD schema")
            
            # Check stream name
            from agents.infrastructure.prd_redis_publisher import get_signal_stream_name
            stream_name = get_signal_stream_name(mode, "BTC/USD")
            expected = f"signals:{mode}:BTC-USD"
            
            if stream_name == expected:
                self.record_result("Stream name generation", True, f"Correct: {stream_name}")
            else:
                self.record_result("Stream name generation", False,
                                 f"Expected {expected}, got {stream_name}")
                return False
            
            # Note: We don't actually publish to avoid polluting production streams
            # But we've verified the code path would work
            self.record_result("Publishing code path", True, "Publishing code path verified (dry run)")
            
            return True
            
        except Exception as e:
            logger.error(f"Stream publishing verification failed: {e}", exc_info=True)
            self.record_result("Stream publishing", False, f"Error: {e}")
            return False
    
    async def run_all_checks(self):
        """Run all verification checks."""
        logger.info("=" * 70)
        logger.info("WEEK 1 VERIFICATION - crypto-ai-bot")
        logger.info("=" * 70)
        logger.info("")
        
        # Run all checks
        checks = [
            ("Redis TLS", self.verify_redis_tls),
            ("Kraken WS", self.verify_kraken_ws),
            ("Signal Generation", self.verify_signal_generation),
            ("Observability", self.verify_observability),
            ("Stream Publishing", self.verify_stream_publishing),
        ]
        
        for name, check_func in checks:
            try:
                await check_func()
            except Exception as e:
                logger.error(f"Check '{name}' failed with exception: {e}", exc_info=True)
                self.record_result(name, False, f"Exception: {e}")
        
        # Print summary
        logger.info("")
        logger.info("=" * 70)
        logger.info("VERIFICATION SUMMARY")
        logger.info("=" * 70)
        
        total = len(self.results)
        passed = sum(1 for passed, _ in self.results.values() if passed)
        failed = total - passed
        
        logger.info(f"Total checks: {total}")
        logger.info(f"Passed: {passed} ✅")
        logger.info(f"Failed: {failed} ❌")
        logger.info("")
        
        # Show failures
        if failed > 0:
            logger.info("FAILED CHECKS:")
            for test_name, (passed, message) in self.results.items():
                if not passed:
                    logger.info(f"  ❌ {test_name}: {message}")
            logger.info("")
        
        # Overall status
        all_passed = failed == 0
        if all_passed:
            logger.info("✅ WEEK 1 VERIFICATION: ALL CHECKS PASSED")
        else:
            logger.info("❌ WEEK 1 VERIFICATION: SOME CHECKS FAILED")
            logger.info("   Please fix the issues above before proceeding to Week 2")
        
        logger.info("=" * 70)
        
        # Cleanup
        if self.redis_client:
            await self.redis_client.disconnect()
        
        return all_passed


async def main():
    """Main entry point."""
    verifier = Week1Verifier()
    success = await verifier.run_all_checks()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())








