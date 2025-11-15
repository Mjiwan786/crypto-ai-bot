#!/usr/bin/env python3
"""
Go-Live Controls Integration Example

Demonstrates how to integrate TradingModeController into your trading agents.
Shows real-world usage patterns for production deployment.

Usage:
    python examples/golive_integration_example.py
"""

import os
import sys
import redis
import logging
from typing import Dict, Any
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from config.trading_mode_controller import (
    TradingModeController,
    TradingMode,
    CircuitBreakerMonitor
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(message)s')
logger = logging.getLogger(__name__)


class TradingAgentWithGoLiveControls:
    """
    Example trading agent with integrated go-live controls.

    Demonstrates:
        - Controller initialization from config
        - Safety checks before signal publishing
        - Emergency stop handling
        - Circuit breaker integration
        - Mode-aware signal routing
    """

    def __init__(self):
        """Initialize agent with go-live controls"""
        # Connect to Redis Cloud
        self.redis = self._connect_redis()

        # Load pair whitelist and notional caps from config
        pair_whitelist = self._load_pair_whitelist()
        notional_caps = self._load_notional_caps()

        # Initialize trading mode controller
        self.mode_controller = TradingModeController(
            redis_client=self.redis,
            pair_whitelist=pair_whitelist,
            notional_caps=notional_caps
        )

        # Initialize circuit breaker monitor
        self.circuit_breaker = CircuitBreakerMonitor(
            redis_client=self.redis,
            mode_controller=self.mode_controller,
            latency_threshold_ms=1000.0,
            spread_threshold_bps=50.0
        )

        logger.info(
            f"Agent initialized in {self.mode_controller.get_current_mode()} mode"
        )

    def _connect_redis(self) -> redis.Redis:
        """Connect to Redis Cloud with TLS"""
        redis_url = os.getenv('REDIS_URL')
        if not redis_url:
            raise ValueError("REDIS_URL not set in environment")

        import ssl
        return redis.from_url(
            redis_url,
            ssl_cert_reqs=ssl.CERT_NONE,
            decode_responses=True
        )

    def _load_pair_whitelist(self):
        """Load pair whitelist from environment"""
        whitelist_str = os.getenv('TRADING_PAIR_WHITELIST', '')
        if not whitelist_str:
            return []
        return [p.strip() for p in whitelist_str.split(',') if p.strip()]

    def _load_notional_caps(self):
        """Load notional caps from environment"""
        caps_str = os.getenv('NOTIONAL_CAPS', '')
        if not caps_str:
            return {}

        caps = {}
        for pair_cap in caps_str.split(','):
            if ':' in pair_cap:
                pair, cap = pair_cap.split(':')
                caps[pair.strip()] = float(cap.strip())
        return caps

    def generate_signal(self, pair: str, side: str, notional_usd: float) -> Dict[str, Any]:
        """
        Generate trading signal with safety checks.

        Args:
            pair: Trading pair (e.g., 'XBTUSD')
            side: 'BUY' or 'SELL'
            notional_usd: Order notional in USD

        Returns:
            Signal dict if published, None if blocked
        """
        logger.info(f"Generating {side} signal for {pair} @ ${notional_usd:.2f}")

        # 1. Check if emergency stop is active
        if self.mode_controller.is_emergency_stop_active():
            logger.error("Emergency stop active - signal blocked")
            return None

        # 2. Run comprehensive safety checks
        safety_check = self.mode_controller.check_can_trade(
            pair=pair,
            notional_usd=notional_usd,
            operation='entry'
        )

        if not safety_check.passed:
            logger.error(f"Safety check failed: {safety_check.errors}")
            return None

        # 3. Build signal
        signal = {
            'timestamp': datetime.utcnow().isoformat(),
            'pair': pair,
            'side': side,
            'notional_usd': notional_usd,
            'mode': safety_check.mode.value,
            'signal_id': f"{pair}-{datetime.utcnow().timestamp()}"
        }

        # 4. Get active signal stream (paper or live)
        stream = self.mode_controller.get_active_signal_stream()

        # 5. Publish to Redis
        self.redis.xadd(stream, signal)

        logger.info(f"✓ Signal published to {stream}: {signal['signal_id']}")

        return signal

    def handle_market_data(
        self,
        pair: str,
        latency_ms: float,
        spread_bps: float,
        price: float
    ):
        """
        Process market data with circuit breaker checks.

        Args:
            pair: Trading pair
            latency_ms: Data latency in milliseconds
            spread_bps: Current spread in basis points
            price: Current price
        """
        # Check latency circuit breaker
        if not self.circuit_breaker.check_latency(latency_ms, pair):
            logger.warning(f"Latency circuit breaker tripped for {pair}")
            return

        # Check spread circuit breaker
        if not self.circuit_breaker.check_spread(spread_bps, pair):
            logger.warning(f"Spread circuit breaker tripped for {pair}")
            return

        # Market data is good - continue processing
        logger.info(
            f"Market data OK: {pair} @ ${price:.2f} "
            f"(latency={latency_ms:.1f}ms, spread={spread_bps:.1f}bps)"
        )

    def switch_to_live_mode(self) -> bool:
        """
        Attempt to switch to LIVE mode.

        Returns:
            True if successful, False otherwise
        """
        logger.warning("Attempting to switch to LIVE mode...")

        if not self.mode_controller.is_live_confirmation_valid():
            logger.error(
                "Cannot switch to LIVE: "
                "LIVE_TRADING_CONFIRMATION='I-accept-the-risk' required"
            )
            return False

        success = self.mode_controller.switch_mode(TradingMode.LIVE)

        if success:
            logger.critical("SWITCHED TO LIVE MODE - REAL MONEY AT RISK")
            return True
        else:
            logger.error("Failed to switch to LIVE mode")
            return False

    def activate_emergency_stop(self, reason: str = "Manual trigger"):
        """Activate emergency kill-switch"""
        logger.critical(f"ACTIVATING EMERGENCY STOP: {reason}")
        self.mode_controller.activate_emergency_stop(reason)

    def get_status(self) -> Dict[str, Any]:
        """Get agent status including go-live control state"""
        return {
            **self.mode_controller.get_status(),
            'agent': 'TradingAgentWithGoLiveControls',
            'redis_connected': self.redis.ping()
        }


def main():
    """Run integration example"""
    logger.info("=" * 60)
    logger.info("Go-Live Controls Integration Example")
    logger.info("=" * 60)

    # Initialize agent
    agent = TradingAgentWithGoLiveControls()

    # Show initial status
    logger.info("\nInitial Status:")
    status = agent.get_status()
    for key, value in status.items():
        logger.info(f"  {key}: {value}")

    # Example 1: Generate signal in PAPER mode
    logger.info("\n" + "=" * 60)
    logger.info("Example 1: Generate Signal in PAPER Mode")
    logger.info("=" * 60)

    signal = agent.generate_signal(
        pair='XBTUSD',
        side='BUY',
        notional_usd=5000.0
    )

    if signal:
        logger.info(f"✓ Signal generated: {signal['signal_id']}")

    # Example 2: Test circuit breakers
    logger.info("\n" + "=" * 60)
    logger.info("Example 2: Test Circuit Breakers")
    logger.info("=" * 60)

    # Good market data
    agent.handle_market_data(
        pair='XBTUSD',
        latency_ms=250.0,
        spread_bps=15.0,
        price=45000.0
    )

    # High latency (should trip breaker)
    agent.handle_market_data(
        pair='XBTUSD',
        latency_ms=1500.0,
        spread_bps=15.0,
        price=45000.0
    )

    # Example 3: Test emergency stop
    logger.info("\n" + "=" * 60)
    logger.info("Example 3: Test Emergency Stop")
    logger.info("=" * 60)

    agent.activate_emergency_stop("Example emergency stop")

    # Try to generate signal (should be blocked)
    signal = agent.generate_signal(
        pair='XBTUSD',
        side='BUY',
        notional_usd=1000.0
    )

    if not signal:
        logger.info("✓ Signal correctly blocked by emergency stop")

    # Deactivate emergency stop
    agent.mode_controller.deactivate_emergency_stop()
    logger.info("Emergency stop deactivated")

    # Example 4: Test pair whitelist (if configured)
    logger.info("\n" + "=" * 60)
    logger.info("Example 4: Test Pair Whitelist")
    logger.info("=" * 60)

    if agent.mode_controller.pair_whitelist:
        # Try allowed pair
        logger.info(f"Whitelisted pairs: {agent.mode_controller.pair_whitelist}")

        allowed_pair = agent.mode_controller.pair_whitelist[0]
        signal = agent.generate_signal(
            pair=allowed_pair,
            side='BUY',
            notional_usd=1000.0
        )

        if signal:
            logger.info(f"✓ Signal allowed for whitelisted pair: {allowed_pair}")

        # Try disallowed pair
        signal = agent.generate_signal(
            pair='FAKEPAIR',
            side='BUY',
            notional_usd=1000.0
        )

        if not signal:
            logger.info("✓ Signal correctly blocked for non-whitelisted pair")
    else:
        logger.info("No whitelist configured - all pairs allowed")

    # Final status
    logger.info("\n" + "=" * 60)
    logger.info("Final Status")
    logger.info("=" * 60)

    status = agent.get_status()
    for key, value in status.items():
        logger.info(f"  {key}: {value}")

    logger.info("\n" + "=" * 60)
    logger.info("Example Complete")
    logger.info("=" * 60)


if __name__ == '__main__':
    main()
