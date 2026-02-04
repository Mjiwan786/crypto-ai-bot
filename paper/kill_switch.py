"""
Kill Switch Manager for Paper Trading.

Provides hierarchical kill switches that immediately stop paper trading:
- Bot kill: disable specific bot's evaluation loop
- Account kill: disable all paper bots for a specific account
- Global paper kill: disable all paper execution loops

Kill switches are stored in Redis (paper namespace) for instant effect.
All kill switch activations are logged with reason.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
import json
import logging

logger = logging.getLogger(__name__)


class KillSwitchType(str, Enum):
    """Types of kill switches."""

    BOT = "bot"
    ACCOUNT = "account"
    GLOBAL = "global"


@dataclass(frozen=True)
class KillSwitchState:
    """State of a kill switch."""

    is_active: bool
    switch_type: KillSwitchType
    target_id: str  # bot_id, account_id, or "paper" for global
    reason: str | None
    activated_at: datetime | None
    activated_by: str | None


# Redis key patterns for kill switches
KILL_SWITCH_KEYS = {
    KillSwitchType.BOT: "kill:bot:{bot_id}",
    KillSwitchType.ACCOUNT: "kill:account:{account_id}",
    KillSwitchType.GLOBAL: "kill:global:paper",
}


class KillSwitchManager:
    """
    Manages paper trading kill switches.

    Kill switches are stored in Redis for immediate effect across all instances.
    Activating a kill switch immediately stops trading and emits a stop event.
    """

    def __init__(self, redis_client: Any):
        """
        Initialize kill switch manager.

        Args:
            redis_client: Async Redis client
        """
        self.redis = redis_client

    def _get_key(
        self,
        switch_type: KillSwitchType,
        target_id: str = "",
    ) -> str:
        """Get Redis key for a kill switch."""
        key_pattern = KILL_SWITCH_KEYS[switch_type]

        if switch_type == KillSwitchType.BOT:
            return key_pattern.format(bot_id=target_id)
        elif switch_type == KillSwitchType.ACCOUNT:
            return key_pattern.format(account_id=target_id)
        else:
            return key_pattern

    async def activate(
        self,
        switch_type: KillSwitchType,
        target_id: str = "",
        reason: str = "Manual kill switch activation",
        activated_by: str = "system",
    ) -> bool:
        """
        Activate a kill switch.

        Args:
            switch_type: Type of kill switch
            target_id: Bot ID or Account ID (ignored for global)
            reason: Reason for activation
            activated_by: User or system that activated

        Returns:
            True if activation successful
        """
        key = self._get_key(switch_type, target_id)

        payload = {
            "active": True,
            "type": switch_type.value,
            "target_id": target_id or "paper",
            "reason": reason,
            "activated_at": datetime.now(timezone.utc).isoformat(),
            "activated_by": activated_by,
        }

        try:
            await self.redis.set(key, json.dumps(payload))

            logger.warning(
                f"Kill switch ACTIVATED: {switch_type.value} target={target_id or 'global'} "
                f"reason={reason} by={activated_by}",
                extra={
                    "kill_switch_type": switch_type.value,
                    "target_id": target_id or "global",
                    "reason": reason,
                    "activated_by": activated_by,
                },
            )
            return True

        except Exception as e:
            logger.error(f"Failed to activate kill switch: {e}")
            return False

    async def deactivate(
        self,
        switch_type: KillSwitchType,
        target_id: str = "",
        deactivated_by: str = "system",
    ) -> bool:
        """
        Deactivate a kill switch.

        Args:
            switch_type: Type of kill switch
            target_id: Bot ID or Account ID (ignored for global)
            deactivated_by: User or system that deactivated

        Returns:
            True if deactivation successful
        """
        key = self._get_key(switch_type, target_id)

        try:
            await self.redis.delete(key)

            logger.info(
                f"Kill switch DEACTIVATED: {switch_type.value} target={target_id or 'global'} "
                f"by={deactivated_by}",
                extra={
                    "kill_switch_type": switch_type.value,
                    "target_id": target_id or "global",
                    "deactivated_by": deactivated_by,
                },
            )
            return True

        except Exception as e:
            logger.error(f"Failed to deactivate kill switch: {e}")
            return False

    async def check(
        self,
        switch_type: KillSwitchType,
        target_id: str = "",
    ) -> KillSwitchState:
        """
        Check state of a kill switch.

        Args:
            switch_type: Type of kill switch
            target_id: Bot ID or Account ID (ignored for global)

        Returns:
            KillSwitchState with current state
        """
        key = self._get_key(switch_type, target_id)

        try:
            data = await self.redis.get(key)

            if data is None:
                return KillSwitchState(
                    is_active=False,
                    switch_type=switch_type,
                    target_id=target_id or "paper",
                    reason=None,
                    activated_at=None,
                    activated_by=None,
                )

            payload = json.loads(data)
            return KillSwitchState(
                is_active=payload.get("active", False),
                switch_type=switch_type,
                target_id=payload.get("target_id", target_id or "paper"),
                reason=payload.get("reason"),
                activated_at=datetime.fromisoformat(payload["activated_at"]) if payload.get("activated_at") else None,
                activated_by=payload.get("activated_by"),
            )

        except Exception as e:
            logger.error(f"Failed to check kill switch: {e}")
            # On error, assume NOT active (fail-open for checking)
            return KillSwitchState(
                is_active=False,
                switch_type=switch_type,
                target_id=target_id or "paper",
                reason=None,
                activated_at=None,
                activated_by=None,
            )

    async def is_trading_blocked(
        self,
        bot_id: str,
        account_id: str,
    ) -> tuple[bool, str | None]:
        """
        Check if trading is blocked by any kill switch.

        Checks in order (most specific to most general):
        1. Bot kill switch
        2. Account kill switch
        3. Global paper kill switch

        Args:
            bot_id: Bot ID to check
            account_id: Account ID to check

        Returns:
            (is_blocked, reason) tuple
        """
        # Check bot kill switch
        bot_state = await self.check(KillSwitchType.BOT, bot_id)
        if bot_state.is_active:
            return True, f"Bot kill switch active: {bot_state.reason}"

        # Check account kill switch
        account_state = await self.check(KillSwitchType.ACCOUNT, account_id)
        if account_state.is_active:
            return True, f"Account kill switch active: {account_state.reason}"

        # Check global paper kill switch
        global_state = await self.check(KillSwitchType.GLOBAL)
        if global_state.is_active:
            return True, f"Global paper kill switch active: {global_state.reason}"

        return False, None


async def check_kill_switch(
    redis_client: Any,
    bot_id: str,
    account_id: str,
) -> tuple[bool, str | None]:
    """
    Convenience function to check if trading is blocked.

    Args:
        redis_client: Async Redis client
        bot_id: Bot ID to check
        account_id: Account ID to check

    Returns:
        (is_blocked, reason) tuple
    """
    manager = KillSwitchManager(redis_client)
    return await manager.is_trading_blocked(bot_id, account_id)
