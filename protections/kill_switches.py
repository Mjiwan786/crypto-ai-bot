"""
Global Kill Switch System with Redis Control

Provides emergency halt capabilities with Redis-based remote control.
Prevents accidental live trading through comprehensive checks.

Features:
- Redis-based kill switch (control:halt_all key with TTL)
- MODE and LIVE_TRADING_CONFIRMATION validation
- Paper mode enforcement
- Emergency halt with immediate effect
"""

import os
import logging
import time
from typing import Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


@dataclass
class TradingMode:
    """Trading mode configuration"""
    mode: str  # "paper" or "live"
    paper_mode: bool
    live_confirmation: str
    is_live_allowed: bool


class GlobalKillSwitch:
    """
    Global kill switch that can halt all trading immediately via Redis control.

    Kill switch can be activated via:
    1. Redis key: control:halt_all with optional TTL
    2. Environment variable: EMERGENCY_HALT=true
    3. Programmatically via activate() method

    Usage:
        kill_switch = GlobalKillSwitch(redis_client)

        # Check before trading
        if not kill_switch.is_trading_allowed():
            raise Exception("Trading halted by kill switch")

        # Activate emergency halt (sets Redis key with 1 hour TTL)
        await kill_switch.activate(reason="Market crash detected", ttl_seconds=3600)

        # Deactivate
        await kill_switch.deactivate()
    """

    REDIS_KEY = "control:halt_all"
    DEFAULT_TTL = 3600  # 1 hour default TTL

    def __init__(self, redis_client=None):
        """
        Initialize global kill switch.

        Args:
            redis_client: Redis client instance (optional, can be set later)
        """
        self.redis_client = redis_client
        self.logger = logging.getLogger(f"{__name__}.GlobalKillSwitch")

        # State tracking
        self.is_active = False
        self.activation_reason = ""
        self.activation_time = 0.0
        self.last_check_time = 0.0
        self.check_interval = 5.0  # Check Redis every 5 seconds

        # Check environment halt flag
        self._check_environment_halt()

        self.logger.info("GlobalKillSwitch initialized")

    def set_redis_client(self, redis_client):
        """Set or update Redis client"""
        self.redis_client = redis_client
        self.logger.info("Redis client configured for kill switch")

    def _check_environment_halt(self):
        """Check if emergency halt is set via environment variable"""
        emergency_halt = os.getenv("EMERGENCY_HALT", "false").lower()
        if emergency_halt == "true":
            self.is_active = True
            self.activation_reason = "Emergency halt via EMERGENCY_HALT environment variable"
            self.activation_time = time.time()
            self.logger.critical(f"🚨 KILL SWITCH ACTIVE: {self.activation_reason}")

    async def check_redis_halt(self) -> Tuple[bool, str]:
        """
        Check Redis for halt command.

        Returns:
            Tuple of (is_halted, reason)
        """
        if not self.redis_client:
            return False, ""

        # Rate limit Redis checks
        current_time = time.time()
        if (current_time - self.last_check_time) < self.check_interval:
            return self.is_active, self.activation_reason

        self.last_check_time = current_time

        try:
            # Check if halt key exists
            halt_value = await self.redis_client.get(self.REDIS_KEY)

            if halt_value:
                # Decode if bytes
                if isinstance(halt_value, bytes):
                    halt_value = halt_value.decode('utf-8')

                reason = f"Redis kill switch activated: {halt_value}"

                # Get TTL to show when it expires
                ttl = await self.redis_client.ttl(self.REDIS_KEY)
                if ttl > 0:
                    reason += f" (expires in {ttl}s)"

                if not self.is_active:
                    # Just activated
                    self.logger.critical(f"🚨 KILL SWITCH ACTIVATED VIA REDIS: {reason}")
                    self.is_active = True
                    self.activation_reason = reason
                    self.activation_time = current_time

                return True, reason
            else:
                # Key doesn't exist, trading allowed
                if self.is_active:
                    # Just deactivated
                    self.logger.warning("✅ Kill switch deactivated via Redis")
                    self.is_active = False
                    self.activation_reason = ""

                return False, ""

        except Exception as e:
            self.logger.error(f"Error checking Redis kill switch: {e}")
            # Fail-safe: if we can't check Redis, don't halt (but log error)
            return False, ""

    async def activate(self, reason: str = "Manual activation", ttl_seconds: Optional[int] = None):
        """
        Activate the kill switch (halts all trading).

        Args:
            reason: Reason for activation
            ttl_seconds: Time-to-live for Redis key (default: 1 hour)
        """
        ttl = ttl_seconds or self.DEFAULT_TTL

        self.is_active = True
        self.activation_reason = reason
        self.activation_time = time.time()

        self.logger.critical(f"🚨 KILL SWITCH ACTIVATED: {reason}")

        # Set Redis key if available
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    self.REDIS_KEY,
                    ttl,
                    f"{reason} (activated at {datetime.now().isoformat()})"
                )
                self.logger.info(f"Redis kill switch key set with TTL={ttl}s")
            except Exception as e:
                self.logger.error(f"Failed to set Redis kill switch: {e}")

    async def deactivate(self):
        """Deactivate the kill switch (resume trading)"""
        self.is_active = False
        self.activation_reason = ""

        self.logger.warning("✅ Kill switch deactivated")

        # Remove Redis key if available
        if self.redis_client:
            try:
                await self.redis_client.delete(self.REDIS_KEY)
                self.logger.info("Redis kill switch key removed")
            except Exception as e:
                self.logger.error(f"Failed to remove Redis kill switch: {e}")

    async def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed (kill switch not active).

        Returns:
            True if trading is allowed, False if halted
        """
        # Check environment halt
        self._check_environment_halt()

        # Check Redis halt
        await self.check_redis_halt()

        return not self.is_active

    def get_status(self) -> dict:
        """Get current kill switch status"""
        return {
            "is_active": self.is_active,
            "reason": self.activation_reason,
            "activation_time": self.activation_time,
            "duration_seconds": time.time() - self.activation_time if self.is_active else 0,
            "redis_key": self.REDIS_KEY,
            "redis_connected": self.redis_client is not None
        }


def check_live_trading_allowed() -> Tuple[bool, str]:
    """
    Check if live trading is allowed based on MODE and LIVE_TRADING_CONFIRMATION.

    Live trading requires:
    1. MODE environment variable set to "live"
    2. LIVE_TRADING_CONFIRMATION set to "I-accept-the-risk"

    Returns:
        Tuple of (is_allowed, error_message)

    Example:
        allowed, error = check_live_trading_allowed()
        if not allowed:
            logger.error(f"Live trading blocked: {error}")
            sys.exit(1)
    """
    mode = os.getenv("MODE", "paper").lower()
    confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")

    # Check if mode is live
    if mode != "live":
        return False, f"MODE is '{mode}', must be 'live' for live trading"

    # Check confirmation string
    if confirmation != "I-accept-the-risk":
        return False, (
            "LIVE_TRADING_CONFIRMATION must be set to 'I-accept-the-risk' for live trading. "
            f"Current value: '{confirmation if confirmation else '(not set)'}'"
        )

    # All checks passed
    logger.warning("⚠️ LIVE TRADING MODE ENABLED - Real money at risk!")
    return True, ""


def get_trading_mode() -> TradingMode:
    """
    Get current trading mode configuration.

    Returns:
        TradingMode object with current configuration
    """
    mode = os.getenv("MODE", "paper").lower()
    confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")

    # Determine if paper mode
    paper_mode = mode != "live"

    # Check if live is allowed
    is_live_allowed, _ = check_live_trading_allowed()

    return TradingMode(
        mode=mode,
        paper_mode=paper_mode,
        live_confirmation=confirmation,
        is_live_allowed=is_live_allowed
    )


def enforce_paper_mode(allow_live: bool = False):
    """
    Decorator to enforce paper mode on functions that execute orders.

    Args:
        allow_live: If True, allows live trading (with confirmation check)

    Example:
        @enforce_paper_mode(allow_live=False)
        def place_order(symbol, size, side):
            # This will only execute in paper mode
            pass
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            mode = get_trading_mode()

            if not mode.paper_mode and not allow_live:
                raise RuntimeError(
                    f"Function '{func.__name__}' requires paper mode. "
                    f"Current mode: {mode.mode}. "
                    "Set MODE=paper to execute this function."
                )

            if not mode.paper_mode and allow_live:
                # Live mode - check confirmation
                allowed, error = check_live_trading_allowed()
                if not allowed:
                    raise RuntimeError(
                        f"Live trading not allowed for '{func.__name__}': {error}"
                    )

            return func(*args, **kwargs)
        return wrapper
    return decorator


# Example usage and testing
async def test_kill_switch():
    """Test kill switch functionality"""
    print("\n=== Testing Global Kill Switch ===\n")

    # Create kill switch without Redis (testing environment halt)
    ks = GlobalKillSwitch()

    print("1. Initial state:")
    print(f"   Trading allowed: {await ks.is_trading_allowed()}")
    print(f"   Status: {ks.get_status()}\n")

    print("2. Activating kill switch...")
    await ks.activate(reason="Testing kill switch", ttl_seconds=300)
    print(f"   Trading allowed: {await ks.is_trading_allowed()}")
    print(f"   Status: {ks.get_status()}\n")

    print("3. Deactivating kill switch...")
    await ks.deactivate()
    print(f"   Trading allowed: {await ks.is_trading_allowed()}")
    print(f"   Status: {ks.get_status()}\n")

    print("4. Testing live trading guards:")
    allowed, error = check_live_trading_allowed()
    print(f"   Live trading allowed: {allowed}")
    if error:
        print(f"   Error: {error}\n")

    print("5. Current trading mode:")
    mode = get_trading_mode()
    print(f"   Mode: {mode.mode}")
    print(f"   Paper mode: {mode.paper_mode}")
    print(f"   Live allowed: {mode.is_live_allowed}\n")


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_kill_switch())
