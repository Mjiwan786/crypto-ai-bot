"""
Tests for News Override Controller

Tests:
- Feature flag on/off paths
- Circuit breaker validation
- Size multiplier application
- TP extension
- Trailing stop logic (only in profit)
- Override expiration
- Metrics tracking
- Audit logging
- Concurrent override limits

Author: Crypto AI Bot Team
Date: 2025-11-08
"""

import os
import time
import unittest
from unittest.mock import Mock, MagicMock, patch

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


# Mock Prometheus metrics to avoid registry collisions
class MockCounter:
    def __init__(self, *args, **kwargs):
        self._value = 0

    def labels(self, **kwargs):
        return self

    def inc(self, amount=1):
        self._value += amount
        return self


class MockGauge:
    def __init__(self, *args, **kwargs):
        self._value = 0

    def set(self, value):
        self._value = value
        return self


class MockHistogram:
    def __init__(self, *args, **kwargs):
        self._observations = []

    def observe(self, value):
        self._observations.append(value)
        return self


def create_mock_metrics():
    """Create a dictionary of mock metrics for testing."""
    return {
        "overrides_created": MockCounter(),
        "overrides_active": MockGauge(),
        "overrides_expired": MockCounter(),
        "size_multiplier_applied": MockHistogram(),
        "tp_extension_applied": MockHistogram(),
        "override_rejections": MockCounter(),
    }


# Import news_reactor classes
from agents.special.news_reactor import (
    NewsOverride,
    NewsOverrideConfig,
    NewsOverrideController,
    NewsSignal,
)


class TestNewsOverrideController(unittest.TestCase):
    """Test NewsOverrideController functionality."""

    def setUp(self):
        """Set up test controller."""
        # Mock Redis and MCP
        self.mock_redis = Mock()
        self.mock_mcp = Mock()

        # Create controller with overrides ENABLED
        config = NewsOverrideConfig(
            enabled=True,
            major_news_sentiment_threshold=0.7,
            max_size_multiplier=1.5,
            tp_extension_seconds=30,
            min_confidence_for_override=0.6,
            override_decay_seconds=300,
            max_concurrent_overrides=3,
        )

        # Create mock metrics
        self.mock_metrics = create_mock_metrics()

        self.controller = NewsOverrideController(
            redis_manager=self.mock_redis,
            mcp=self.mock_mcp,
            config=config,
            metrics=self.mock_metrics,
        )

        # Sample news signal
        self.major_news_signal = NewsSignal(
            signal_id="signal-123",
            symbol="BTC/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Bitcoin ETF Approved by SEC",
        )

    def test_feature_flag_disabled(self):
        """Test that overrides are blocked when feature flag is disabled."""
        # Create controller with overrides DISABLED
        config = NewsOverrideConfig(enabled=False)
        mock_metrics = create_mock_metrics()
        controller = NewsOverrideController(config=config, metrics=mock_metrics)

        # Try to create override
        override = controller.create_override(self.major_news_signal)

        # Should be None
        self.assertIsNone(override)

        # Check reason
        should_apply, reason = controller.should_apply_override(
            self.major_news_signal, 0.0, False
        )
        self.assertFalse(should_apply)
        self.assertIn("disabled", reason.lower())

    def test_feature_flag_enabled(self):
        """Test that overrides work when feature flag is enabled."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)

        # Should be created
        self.assertIsNotNone(override)
        self.assertEqual(override.symbol, "BTC/USD")
        self.assertTrue(override.is_active)

    def test_circuit_breaker_blocks_overrides(self):
        """Test that circuit breaker blocks override creation."""
        # Try to create override with circuit breaker active
        override = self.controller.create_override(
            self.major_news_signal, circuit_breaker_active=True
        )

        # Should be None
        self.assertIsNone(override)

        # Check reason
        should_apply, reason = self.controller.should_apply_override(
            self.major_news_signal, 0.0, circuit_breaker_active=True
        )
        self.assertFalse(should_apply)
        self.assertIn("circuit breaker", reason.lower())

    def test_circuit_breaker_blocks_size_application(self):
        """Test that circuit breaker blocks size multiplier application."""
        # Create override first (without circuit breaker)
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Try to apply size with circuit breaker active
        base_size = 1000.0
        adjusted_size, override_id = self.controller.apply_size_override(
            base_size, "BTC/USD", circuit_breaker_active=True
        )

        # Should return base size (no override applied)
        self.assertEqual(adjusted_size, base_size)
        self.assertIsNone(override_id)

    def test_circuit_breaker_blocks_tp_application(self):
        """Test that circuit breaker blocks TP extension application."""
        # Create override first (without circuit breaker)
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Try to apply TP with circuit breaker active
        base_tp = 60
        adjusted_tp, override_id = self.controller.apply_tp_override(
            base_tp, "BTC/USD", circuit_breaker_active=True
        )

        # Should return base TP (no override applied)
        self.assertEqual(adjusted_tp, base_tp)
        self.assertIsNone(override_id)

    def test_major_news_detection(self):
        """Test major news detection logic."""
        # Test with major news (high sentiment + confidence)
        is_major = self.controller.check_major_news_detected(self.major_news_signal)
        self.assertTrue(is_major)

        # Test with low sentiment
        weak_signal = NewsSignal(
            signal_id="signal-456",
            symbol="BTC/USD",
            sentiment=0.3,  # Below threshold
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Bitcoin price slightly up",
        )

        is_major = self.controller.check_major_news_detected(weak_signal)
        self.assertFalse(is_major)

        # Test with low confidence
        low_confidence_signal = NewsSignal(
            signal_id="signal-789",
            symbol="BTC/USD",
            sentiment=0.85,
            confidence=0.3,  # Below threshold
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Bitcoin rumored to...",
        )

        is_major = self.controller.check_major_news_detected(low_confidence_signal)
        self.assertFalse(is_major)

    def test_size_multiplier_calculation(self):
        """Test size multiplier calculation."""
        # Calculate multiplier
        multiplier = self.controller.calculate_size_multiplier(self.major_news_signal)

        # Should be between 1.0 and 1.5
        self.assertGreaterEqual(multiplier, 1.0)
        self.assertLessEqual(multiplier, 1.5)

        # Should increase with signal strength
        # sentiment=0.85, confidence=0.75, strength=0.80 -> multiplier ~1.255
        self.assertGreater(multiplier, 1.2)

    def test_size_multiplier_application(self):
        """Test size multiplier application."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Apply size override
        base_size = 1000.0
        adjusted_size, override_id = self.controller.apply_size_override(
            base_size, "BTC/USD"
        )

        # Should be increased
        self.assertGreater(adjusted_size, base_size)
        self.assertLessEqual(adjusted_size, base_size * 1.5)
        self.assertEqual(override_id, override.override_id)

    def test_tp_extension_calculation(self):
        """Test TP extension calculation."""
        # Calculate extension
        extension = self.controller.calculate_tp_extension(self.major_news_signal)

        # Should be between 0 and config max (30)
        self.assertGreaterEqual(extension, 0)
        self.assertLessEqual(extension, 30)

        # Should increase with signal quality (confidence * strength)
        # confidence=0.75, strength=0.80 -> high extension
        self.assertGreater(extension, 15)

    def test_tp_extension_application(self):
        """Test TP extension application."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Apply TP override
        base_tp = 60
        adjusted_tp, override_id = self.controller.apply_tp_override(
            base_tp, "BTC/USD"
        )

        # Should be extended
        self.assertGreater(adjusted_tp, base_tp)
        self.assertEqual(override_id, override.override_id)

    def test_trailing_stop_only_in_profit(self):
        """Test that trailing stop only activates in profit."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Test long position in profit
        should_trail = self.controller.should_trail_stop(
            "BTC/USD",
            entry_price=50000.0,
            current_price=51000.0,  # In profit
            side="long",
        )
        self.assertTrue(should_trail)

        # Test long position NOT in profit
        should_trail = self.controller.should_trail_stop(
            "BTC/USD",
            entry_price=50000.0,
            current_price=49000.0,  # Not in profit
            side="long",
        )
        self.assertFalse(should_trail)

        # Test short position in profit
        should_trail = self.controller.should_trail_stop(
            "BTC/USD",
            entry_price=50000.0,
            current_price=49000.0,  # In profit
            side="short",
        )
        self.assertTrue(should_trail)

        # Test short position NOT in profit
        should_trail = self.controller.should_trail_stop(
            "BTC/USD",
            entry_price=50000.0,
            current_price=51000.0,  # Not in profit
            side="short",
        )
        self.assertFalse(should_trail)

    def test_override_expiration(self):
        """Test override expiration."""
        # Create controller with short decay
        config = NewsOverrideConfig(
            enabled=True,
            override_decay_seconds=60,  # minimum allowed
        )
        mock_metrics = create_mock_metrics()
        controller = NewsOverrideController(config=config, metrics=mock_metrics)

        # Create override
        override = controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Should be active
        active_override = controller.get_active_override("BTC/USD")
        self.assertIsNotNone(active_override)

        # Manually expire the override by setting expires_at to past
        override.expires_at = time.time() - 1
        override.is_active = False

        # Should be expired
        active_override = controller.get_active_override("BTC/USD")
        self.assertIsNone(active_override)

    def test_max_concurrent_overrides(self):
        """Test max concurrent overrides limit."""
        # Create controller with max 2 concurrent
        config = NewsOverrideConfig(enabled=True, max_concurrent_overrides=2)
        mock_metrics = create_mock_metrics()
        controller = NewsOverrideController(config=config, metrics=mock_metrics)

        # Create first override
        signal1 = NewsSignal(
            signal_id="signal-1",
            symbol="BTC/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="BTC News 1",
        )
        override1 = controller.create_override(signal1)
        self.assertIsNotNone(override1)

        # Create second override (different symbol)
        signal2 = NewsSignal(
            signal_id="signal-2",
            symbol="ETH/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="ETH News 1",
        )
        override2 = controller.create_override(signal2)
        self.assertIsNotNone(override2)

        # Try to create third override (should fail - at limit)
        signal3 = NewsSignal(
            signal_id="signal-3",
            symbol="SOL/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="SOL News 1",
        )
        override3 = controller.create_override(signal3)
        self.assertIsNone(override3)

    def test_duplicate_symbol_override_rejection(self):
        """Test that duplicate symbol overrides are rejected."""
        # Create first override
        override1 = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override1)

        # Try to create second override for same symbol
        signal2 = NewsSignal(
            signal_id="signal-456",
            symbol="BTC/USD",  # Same symbol
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Another BTC news",
        )
        override2 = self.controller.create_override(signal2)
        self.assertIsNone(override2)

    def test_metrics_tracking(self):
        """Test metrics are tracked correctly."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Check metrics exist
        self.assertIn("overrides_created", self.controller.metrics)
        self.assertIn("overrides_active", self.controller.metrics)
        self.assertIn("size_multiplier_applied", self.controller.metrics)
        self.assertIn("tp_extension_applied", self.controller.metrics)

    def test_audit_logging(self):
        """Test audit logging."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Check audit log
        audit_log = self.controller.get_audit_log()
        self.assertGreater(len(audit_log), 0)

        # Find creation event
        creation_events = [e for e in audit_log if e["event_type"] == "override_created"]
        self.assertEqual(len(creation_events), 1)

        # Verify event data
        event = creation_events[0]
        self.assertEqual(event["data"]["symbol"], "BTC/USD")
        self.assertEqual(event["data"]["signal_id"], "signal-123")

    def test_override_summary(self):
        """Test override summary generation."""
        # Create override
        override = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override)

        # Get summary
        summary = self.controller.get_override_summary()

        # Verify summary
        self.assertTrue(summary["enabled"])
        self.assertEqual(summary["active_count"], 1)
        self.assertEqual(summary["max_concurrent"], 3)
        self.assertEqual(len(summary["active_overrides"]), 1)

        # Verify override details
        active = summary["active_overrides"][0]
        self.assertEqual(active["symbol"], "BTC/USD")
        self.assertGreater(active["size_multiplier"], 1.0)
        self.assertGreater(active["tp_extension_seconds"], 0)

    def test_disable_all_overrides(self):
        """Test emergency disable all overrides."""
        # Create overrides
        override1 = self.controller.create_override(self.major_news_signal)
        self.assertIsNotNone(override1)

        signal2 = NewsSignal(
            signal_id="signal-456",
            symbol="ETH/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="ETH news",
        )
        override2 = self.controller.create_override(signal2)
        self.assertIsNotNone(override2)

        # Verify both active
        summary = self.controller.get_override_summary()
        self.assertEqual(summary["active_count"], 2)

        # Disable all
        self.controller.disable_all_overrides("Emergency stop")

        # Verify all disabled
        summary = self.controller.get_override_summary()
        self.assertEqual(summary["active_count"], 0)

        # Check audit log
        audit_log = self.controller.get_audit_log()
        disabled_events = [e for e in audit_log if e["event_type"] == "override_disabled"]
        self.assertEqual(len(disabled_events), 2)

    def test_environment_variable_configuration(self):
        """Test configuration from environment variables."""
        # Set environment variables
        with patch.dict(
            os.environ,
            {
                "NEWS_OVERRIDES_ENABLED": "true",
                "NEWS_SENTIMENT_THRESHOLD": "0.8",
                "NEWS_MAX_SIZE_MULTIPLIER": "1.4",
                "NEWS_TP_EXTENSION_SECONDS": "45",
            },
        ):
            # Create controller
            mock_metrics = create_mock_metrics()
            controller = NewsOverrideController(metrics=mock_metrics)

            # Verify configuration
            self.assertTrue(controller.enabled)
            self.assertEqual(controller.config.major_news_sentiment_threshold, 0.8)
            self.assertEqual(controller.config.max_size_multiplier, 1.4)
            self.assertEqual(controller.config.tp_extension_seconds, 45)

    def test_no_override_for_minor_news(self):
        """Test that minor news does not create overrides."""
        # Create minor news signal (low sentiment)
        minor_news = NewsSignal(
            signal_id="signal-minor",
            symbol="BTC/USD",
            sentiment=0.3,  # Low sentiment
            confidence=0.5,
            direction="bullish",
            strength=0.4,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Bitcoin price ticks up slightly",
        )

        # Try to create override
        override = self.controller.create_override(minor_news)

        # Should be None
        self.assertIsNone(override)

    def test_override_without_active_override(self):
        """Test applying override when no override is active."""
        # Try to apply size without creating override
        base_size = 1000.0
        adjusted_size, override_id = self.controller.apply_size_override(
            base_size, "BTC/USD"
        )

        # Should return base size
        self.assertEqual(adjusted_size, base_size)
        self.assertIsNone(override_id)

        # Try to apply TP without creating override
        base_tp = 60
        adjusted_tp, override_id = self.controller.apply_tp_override(base_tp, "BTC/USD")

        # Should return base TP
        self.assertEqual(adjusted_tp, base_tp)
        self.assertIsNone(override_id)


class TestNewsOverrideIntegration(unittest.TestCase):
    """Integration tests for news override workflow."""

    def test_full_override_lifecycle(self):
        """Test full lifecycle: create, apply, expire."""
        # Create controller with short decay (minimum 60 seconds)
        config = NewsOverrideConfig(enabled=True, override_decay_seconds=60)
        mock_metrics = create_mock_metrics()
        controller = NewsOverrideController(config=config, metrics=mock_metrics)

        # Create news signal
        signal = NewsSignal(
            signal_id="lifecycle-test",
            symbol="BTC/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Major Bitcoin News",
        )

        # 1. Create override
        override = controller.create_override(signal)
        self.assertIsNotNone(override)

        # 2. Apply size override
        base_size = 1000.0
        adjusted_size, _ = controller.apply_size_override(base_size, "BTC/USD")
        self.assertGreater(adjusted_size, base_size)

        # 3. Apply TP override
        base_tp = 60
        adjusted_tp, _ = controller.apply_tp_override(base_tp, "BTC/USD")
        self.assertGreater(adjusted_tp, base_tp)

        # 4. Check trailing stop (in profit)
        should_trail = controller.should_trail_stop(
            "BTC/USD", entry_price=50000.0, current_price=51000.0, side="long"
        )
        self.assertTrue(should_trail)

        # 5. Manually expire the override
        override.expires_at = time.time() - 1
        override.is_active = False

        # 6. Verify expired
        active_override = controller.get_active_override("BTC/USD")
        self.assertIsNone(active_override)

        # 7. Verify overrides no longer apply
        adjusted_size, _ = controller.apply_size_override(base_size, "BTC/USD")
        self.assertEqual(adjusted_size, base_size)

    def test_circuit_breaker_safety(self):
        """Test that circuit breaker prevents all override operations."""
        config = NewsOverrideConfig(enabled=True)
        mock_metrics = create_mock_metrics()
        controller = NewsOverrideController(config=config, metrics=mock_metrics)

        signal = NewsSignal(
            signal_id="cb-test",
            symbol="BTC/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="Bitcoin Rally",
        )

        # Circuit breaker OFF - should work
        override = controller.create_override(signal, circuit_breaker_active=False)
        self.assertIsNotNone(override)

        # Create another signal for testing with CB on
        signal2 = NewsSignal(
            signal_id="cb-test-2",
            symbol="ETH/USD",
            sentiment=0.85,
            confidence=0.75,
            direction="bullish",
            strength=0.80,
            half_life=12.0,
            created_at=time.time(),
            expires_at=time.time() + 3600,
            headline="ETH Rally",
        )

        # Circuit breaker ON - should block creation
        override2 = controller.create_override(signal2, circuit_breaker_active=True)
        self.assertIsNone(override2)

        # Circuit breaker ON - should block size application
        base_size = 1000.0
        adjusted_size, _ = controller.apply_size_override(
            base_size, "BTC/USD", circuit_breaker_active=True
        )
        self.assertEqual(adjusted_size, base_size)

        # Circuit breaker ON - should block TP application
        base_tp = 60
        adjusted_tp, _ = controller.apply_tp_override(
            base_tp, "BTC/USD", circuit_breaker_active=True
        )
        self.assertEqual(adjusted_tp, base_tp)


if __name__ == "__main__":
    unittest.main()
