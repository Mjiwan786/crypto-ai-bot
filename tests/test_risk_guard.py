"""
Tests for RiskGuard - Pre-Order Risk Validation

Run with:
    pytest tests/test_risk_guard.py -v
    python tests/test_risk_guard.py
"""

import os
import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def test_default_config_safe():
    """Test that default config has safe values."""
    from protections.risk_guard import RiskConfig

    config = RiskConfig.from_env()

    # Safe defaults
    assert config.live_trading_enabled is False, "Should default to disabled"
    assert config.max_position_size_usd == 25.0
    assert config.max_daily_loss_usd == 2.0
    assert config.max_trades_per_day == 8
    assert config.risk_per_trade_pct == 0.5
    assert config.emergency_stop is False
    assert config.cooldown_seconds_after_loss == 300


def test_live_trading_disabled_by_default():
    """Test that trading is blocked when LIVE_TRADING_ENABLED=false."""
    os.environ.pop("LIVE_TRADING_ENABLED", None)

    from protections.risk_guard import RiskGuard

    guard = RiskGuard()
    result = guard.check_order(position_size_usd=10.0)

    assert result.allowed is False
    assert result.limit_hit == "live_trading_disabled"


def test_emergency_stop_blocks_orders():
    """Test that EMERGENCY_STOP=true blocks all orders."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=True,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    result = guard.check_order(position_size_usd=10.0)

    assert result.allowed is False
    assert result.limit_hit == "emergency_stop"


def test_emergency_stop_allows_exits():
    """Test that exits are allowed during emergency stop."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=True,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    result = guard.check_order(position_size_usd=10.0, is_exit=True)

    assert result.allowed is True


def test_max_position_size_enforced():
    """Test that max position size is enforced."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=False,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    # Under limit - allowed
    result = guard.check_order(position_size_usd=20.0)
    assert result.allowed is True

    # Over limit - blocked
    result = guard.check_order(position_size_usd=30.0)
    assert result.allowed is False
    assert result.limit_hit == "max_position_size"


def test_max_daily_loss_enforced():
    """Test that max daily loss is enforced."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=False,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    # Under limit - allowed
    result = guard.check_order(position_size_usd=10.0, daily_pnl=-1.0)
    assert result.allowed is True

    # Over limit - blocked
    result = guard.check_order(position_size_usd=10.0, daily_pnl=-2.5)
    assert result.allowed is False
    assert result.limit_hit == "max_daily_loss"


def test_max_trades_per_day_enforced():
    """Test that max trades per day is enforced."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=False,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    # Under limit - allowed
    result = guard.check_order(position_size_usd=10.0, trades_today=5)
    assert result.allowed is True

    # At limit - blocked
    result = guard.check_order(position_size_usd=10.0, trades_today=8)
    assert result.allowed is False
    assert result.limit_hit == "max_trades_per_day"


def test_connection_health_blocks_when_unhealthy():
    """Test that unhealthy connection blocks execution."""
    from protections.risk_guard import RiskConfig, RiskGuard

    config = RiskConfig(
        live_trading_enabled=True,
        max_position_size_usd=25.0,
        max_daily_loss_usd=2.0,
        risk_per_trade_pct=0.5,
        max_trades_per_day=8,
        emergency_stop=False,
        cooldown_seconds_after_loss=300,
    )
    guard = RiskGuard(config=config)

    # Set unhealthy
    guard.set_connection_health(False)

    result = guard.check_order(position_size_usd=10.0)
    assert result.allowed is False
    assert result.limit_hit == "connection_health"

    # Exits still allowed
    result = guard.check_order(position_size_usd=10.0, is_exit=True)
    assert result.allowed is True


def test_startup_log_no_secrets():
    """Test that startup log doesn't expose secrets."""
    import io
    import logging

    from protections.risk_guard import RiskGuard

    guard = RiskGuard()

    # Capture log output
    log_stream = io.StringIO()
    handler = logging.StreamHandler(log_stream)
    handler.setLevel(logging.INFO)
    guard.logger.addHandler(handler)

    guard.log_active_limits()

    log_output = log_stream.getvalue()

    # Should contain trading status (log format may vary)
    assert "LIVE_TRADING_ENABLED" in log_output or "live" in log_output.lower()

    # Should NOT contain secrets
    assert "api_key" not in log_output.lower()
    assert "api_secret" not in log_output.lower()
    assert "password" not in log_output.lower()
    assert "KRAKEN_API" not in log_output

    guard.logger.removeHandler(handler)


# =============================================================================
# SHADOW EXECUTION MODE TESTS
# =============================================================================


def test_execution_gate_preflight_logging():
    """Test that ExecutionGate logs non-sensitive preflight status."""
    import io
    import logging
    import os

    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["EMERGENCY_STOP"] = "false"
    os.environ["MAX_POSITION_SIZE_USD"] = "25"

    try:
        from protections.execution_gate import ExecutionGate, reset_execution_gate

        reset_execution_gate()
        gate = ExecutionGate()

        # Capture log output - ensure logger level is set
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        gate.logger.setLevel(logging.DEBUG)
        gate.logger.addHandler(handler)

        gate.log_preflight_status()

        log_output = log_stream.getvalue()

        # Should contain key status info (case insensitive check)
        log_lower = log_output.lower()
        assert "live_trading_enabled" in log_lower or "live" in log_lower
        assert "emergency_stop" in log_lower or "emergency" in log_lower
        assert "max_position_size" in log_lower or "25" in log_output

        # Should NOT contain secrets
        assert "api_key" not in log_lower
        assert "api_secret" not in log_lower

        gate.logger.removeHandler(handler)

    finally:
        os.environ.pop("LIVE_TRADING_ENABLED", None)
        os.environ.pop("EMERGENCY_STOP", None)
        os.environ.pop("MAX_POSITION_SIZE_USD", None)


def test_execution_gate_dry_run_logging():
    """Test that dry-run mode logs 'would place order'."""
    import io
    import logging
    import os

    os.environ["LIVE_TRADING_ENABLED"] = "false"

    try:
        from protections.execution_gate import ExecutionGate, reset_execution_gate

        reset_execution_gate()
        gate = ExecutionGate()

        # Capture log output - ensure logger level is set
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        handler.setLevel(logging.DEBUG)
        gate.logger.setLevel(logging.DEBUG)
        gate.logger.addHandler(handler)

        gate.log_dry_run_order({
            "symbol": "BTC/USD",
            "side": "buy",
            "size": 0.001,
            "price": 50000.0,
        })

        log_output = log_stream.getvalue()

        # Should contain "DRY-RUN" and "would place"
        assert "DRY-RUN" in log_output
        assert "would place" in log_output
        assert "BTC/USD" in log_output

        gate.logger.removeHandler(handler)

    finally:
        os.environ.pop("LIVE_TRADING_ENABLED", None)


def test_execution_gate_blocks_when_disabled():
    """Test that ExecutionGate blocks orders when LIVE_TRADING_ENABLED=false."""
    import os

    os.environ["LIVE_TRADING_ENABLED"] = "false"

    try:
        from protections.execution_gate import ExecutionGate, reset_execution_gate

        reset_execution_gate()
        gate = ExecutionGate()

        result = gate.check(position_size_usd=10.0)

        assert not result.allowed
        assert result.dry_run  # Should be marked as dry-run
        assert "LIVE_TRADING_ENABLED" in result.reason

    finally:
        os.environ.pop("LIVE_TRADING_ENABLED", None)


def test_execution_gate_shadow_mode():
    """Test that ExecutionGate returns shadow_mode=true when enabled."""
    import os

    os.environ["LIVE_TRADING_ENABLED"] = "true"
    os.environ["SHADOW_EXECUTION"] = "true"
    os.environ["MODE"] = "live"
    os.environ["LIVE_TRADING_CONFIRMATION"] = "I-accept-the-risk"

    try:
        from protections.execution_gate import ExecutionGate, reset_execution_gate

        reset_execution_gate()
        gate = ExecutionGate()

        result = gate.check(position_size_usd=10.0)

        # Shadow mode should be allowed but marked as shadow
        assert result.allowed
        assert result.shadow_mode

    finally:
        os.environ.pop("LIVE_TRADING_ENABLED", None)
        os.environ.pop("SHADOW_EXECUTION", None)
        os.environ.pop("MODE", None)
        os.environ.pop("LIVE_TRADING_CONFIRMATION", None)


def test_emergency_stop_blocks_before_shadow():
    """Test that EMERGENCY_STOP blocks orders even when shadow mode is enabled."""
    import os

    os.environ["EMERGENCY_STOP"] = "true"
    os.environ["SHADOW_EXECUTION"] = "true"
    os.environ["LIVE_TRADING_ENABLED"] = "true"

    try:
        from protections.risk_guard import RiskGuard

        guard = RiskGuard()
        result = guard.check_order(position_size_usd=10.0)

        # Emergency stop should block
        assert not result.allowed
        assert "EMERGENCY" in result.reason.upper()

    finally:
        os.environ.pop("EMERGENCY_STOP", None)
        os.environ.pop("SHADOW_EXECUTION", None)
        os.environ.pop("LIVE_TRADING_ENABLED", None)


def test_live_trading_disabled_blocks_before_shadow():
    """Test that LIVE_TRADING_ENABLED=false blocks even with shadow mode."""
    import os

    os.environ["LIVE_TRADING_ENABLED"] = "false"
    os.environ["SHADOW_EXECUTION"] = "true"

    try:
        from protections.risk_guard import RiskGuard

        guard = RiskGuard()
        result = guard.check_order(position_size_usd=10.0)

        # Live trading disabled should block
        assert not result.allowed
        assert "LIVE_TRADING_ENABLED" in result.reason or "disabled" in result.reason.lower()

    finally:
        os.environ.pop("LIVE_TRADING_ENABLED", None)
        os.environ.pop("SHADOW_EXECUTION", None)


# =============================================================================
# SHADOW AUDIT TRAIL TESTS
# =============================================================================


def test_shadow_recorder_creates_audit_event():
    """Test that ShadowOrderRecorder creates complete audit events."""
    from protections.shadow_recorder import ShadowOrderRecorder, reset_shadow_recorder

    reset_shadow_recorder()
    recorder = ShadowOrderRecorder()

    event = recorder.record_shadow_order(
        shadow_order_id="SHADOW-TEST123",
        symbol="BTC/USD",
        side="buy",
        size=0.001,
        price=50000.0,
        order_type="limit",
        client_order_id="client-123",
        reason="scalp_signal",
        risk_check_passed=True,
        risk_check_details={"notional_usd": 50.0, "within_limits": True},
        gate_allowed=True,
    )

    # Verify all required audit fields are present
    assert event.shadow_order_id == "SHADOW-TEST123"
    assert event.timestamp is not None  # ISO 8601 format
    assert event.timestamp_unix > 0
    assert event.symbol == "BTC/USD"
    assert event.side == "buy"
    assert event.size == 0.001
    assert event.price == 50000.0
    assert event.notional_usd == 50.0
    assert event.reason == "scalp_signal"
    assert event.risk_check_passed is True
    assert event.gate_allowed is True
    assert event.would_execute is True
    assert event.execution_mode == "shadow"


def test_shadow_recorder_audit_log_line():
    """Test that audit log line contains all required fields."""
    from protections.shadow_recorder import ShadowOrderRecorder, reset_shadow_recorder

    reset_shadow_recorder()
    recorder = ShadowOrderRecorder()

    event = recorder.record_shadow_order(
        shadow_order_id="SHADOW-AUDIT456",
        symbol="ETH/USD",
        side="sell",
        size=1.5,
        price=3000.0,
        reason="rebalance",
        risk_check_passed=True,
        gate_allowed=True,
    )

    log_line = event.to_log_line()

    # Verify log line contains all required audit fields
    assert "SHADOW_AUDIT" in log_line
    assert "SHADOW-AUDIT456" in log_line
    assert "ETH/USD" in log_line
    assert "SELL" in log_line
    assert "1.5" in log_line
    assert "3000" in log_line
    assert "reason=rebalance" in log_line
    assert "risk=PASS" in log_line
    assert "gate=ALLOW" in log_line
    assert "would_execute=True" in log_line


def test_shadow_recorder_blocked_order_audit():
    """Test that blocked shadow orders are properly recorded."""
    from protections.shadow_recorder import ShadowOrderRecorder, reset_shadow_recorder

    reset_shadow_recorder()
    recorder = ShadowOrderRecorder()

    event = recorder.record_shadow_order(
        shadow_order_id="SHADOW-BLOCKED789",
        symbol="SOL/USD",
        side="buy",
        size=100.0,
        price=150.0,
        reason="scalp_signal",
        risk_check_passed=False,
        risk_check_details={"reason": "position_too_large"},
        gate_allowed=False,
        gate_name="max_position_size",
        gate_reason="Position too large: $15000 > $25",
    )

    # Verify blocked order audit
    assert event.risk_check_passed is False
    assert event.gate_allowed is False
    assert event.gate_name == "max_position_size"
    assert event.would_execute is False

    log_line = event.to_log_line()
    assert "risk=FAIL" in log_line
    assert "gate=BLOCK:max_position_size" in log_line
    assert "would_execute=False" in log_line


def test_shadow_recorder_event_buffer():
    """Test that recorder maintains event buffer and summary."""
    from protections.shadow_recorder import ShadowOrderRecorder, reset_shadow_recorder

    reset_shadow_recorder()
    recorder = ShadowOrderRecorder(max_events=10)

    # Record multiple events
    for i in range(5):
        recorder.record_shadow_order(
            shadow_order_id=f"SHADOW-BUFFER{i}",
            symbol="BTC/USD",
            side="buy" if i % 2 == 0 else "sell",
            size=0.001,
            price=50000.0 + i * 100,
            reason="test",
            risk_check_passed=True,
            gate_allowed=True,
        )

    # Verify event count
    assert recorder.get_event_count() == 5

    # Verify recent events
    events = recorder.get_recent_events(limit=3)
    assert len(events) == 3

    # Verify summary
    summary = recorder.get_summary()
    assert summary["total_events"] == 5
    assert summary["would_execute_count"] == 5
    assert summary["blocked_count"] == 0
    assert "BTC/USD" in summary["symbols"]


def test_shadow_recorder_json_export():
    """Test that shadow events can be exported to JSON."""
    from protections.shadow_recorder import ShadowOrderRecorder, reset_shadow_recorder
    import json

    reset_shadow_recorder()
    recorder = ShadowOrderRecorder()

    recorder.record_shadow_order(
        shadow_order_id="SHADOW-EXPORT1",
        symbol="BTC/USD",
        side="buy",
        size=0.001,
        price=50000.0,
        reason="test",
        risk_check_passed=True,
        gate_allowed=True,
    )

    json_str = recorder.export_to_json()
    data = json.loads(json_str)

    assert len(data) == 1
    assert data[0]["shadow_order_id"] == "SHADOW-EXPORT1"
    assert data[0]["symbol"] == "BTC/USD"
    assert data[0]["would_execute"] is True


def test_shadow_event_to_dict():
    """Test that ShadowOrderEvent converts to dict properly."""
    from protections.shadow_recorder import ShadowOrderEvent

    event = ShadowOrderEvent(
        shadow_order_id="SHADOW-DICT1",
        client_order_id="client-1",
        timestamp="2025-01-01T00:00:00Z",
        timestamp_unix=1735689600.0,
        symbol="BTC/USD",
        side="buy",
        order_type="limit",
        size=0.001,
        price=50000.0,
        notional_usd=50.0,
        reason="test",
        risk_check_passed=True,
        gate_allowed=True,
        would_execute=True,
    )

    d = event.to_dict()

    assert d["shadow_order_id"] == "SHADOW-DICT1"
    assert d["symbol"] == "BTC/USD"
    assert d["notional_usd"] == 50.0
    assert d["would_execute"] is True


if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    print("\n" + "=" * 60)
    print("RISK GUARD - UNIT TESTS")
    print("=" * 60)

    tests = [
        ("Default config safe", test_default_config_safe),
        ("Live trading disabled by default", test_live_trading_disabled_by_default),
        ("Emergency stop blocks orders", test_emergency_stop_blocks_orders),
        ("Emergency stop allows exits", test_emergency_stop_allows_exits),
        ("Max position size enforced", test_max_position_size_enforced),
        ("Max daily loss enforced", test_max_daily_loss_enforced),
        ("Max trades per day enforced", test_max_trades_per_day_enforced),
        ("Connection health blocks when unhealthy", test_connection_health_blocks_when_unhealthy),
        ("Startup log no secrets", test_startup_log_no_secrets),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        try:
            test_func()
            print(f"  [OK] {name}")
            passed += 1
        except Exception as e:
            print(f"  [FAIL] {name}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"SUMMARY: {passed} passed, {failed} failed")
    print("=" * 60)

    sys.exit(1 if failed > 0 else 0)
