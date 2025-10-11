#!/usr/bin/env python3
"""Test configuration loader functionality."""

import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

# Force UTF-8 encoding for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def test_basic_import():
    """Test basic imports work."""
    print("\n1. Testing basic imports...")
    from agents.config.config_loader import (
        load_agent_settings,
        Settings,
        RedisSettings,
        KrakenSettings,
        RiskSettings,
        ScalperSettings,
    )
    print("   PASS: All imports successful")


def test_default_settings():
    """Test loading default settings."""
    print("\n2. Testing default settings (paper mode)...")
    from agents.config.config_loader import load_agent_settings

    # Clear any existing MODE/LIVE_TRADING_CONFIRMATION env vars
    env = {k: v for k, v in os.environ.items()
           if k not in ("MODE", "LIVE_TRADING_CONFIRMATION")}

    settings = load_agent_settings(env=env)

    assert settings.mode == "paper", f"Expected paper mode, got {settings.mode}"
    assert settings.redis.url == "redis://localhost:6379"
    assert settings.kraken.api_url == "https://api.kraken.com"
    assert settings.risk.max_leverage == 1.0
    assert settings.scalper.enabled is True

    print("   PASS: Default settings loaded correctly")
    print(f"   - mode: {settings.mode}")
    print(f"   - redis.url: {settings.redis.url}")
    print(f"   - risk.max_leverage: {settings.risk.max_leverage}")


def test_env_override():
    """Test environment variable overrides."""
    print("\n3. Testing environment variable overrides...")
    from agents.config.config_loader import load_agent_settings

    env = {
        "MODE": "paper",
        "REDIS_URL": "redis://testhost:6379",
        "KRAKEN_API_URL": "https://test.kraken.com",
        "RISK_MAX_LEVERAGE": "2.5",
        "SCALP_MAX_TOXICITY_SCORE": "0.7",
    }

    settings = load_agent_settings(env=env)

    assert settings.redis.url == "redis://testhost:6379"
    assert settings.kraken.api_url == "https://test.kraken.com"
    assert settings.risk.max_leverage == 2.5
    assert settings.scalper.max_toxicity_score == 0.7

    print("   PASS: Environment overrides working")
    print(f"   - redis.url: {settings.redis.url}")
    print(f"   - risk.max_leverage: {settings.risk.max_leverage}")


def test_yaml_loading():
    """Test YAML file loading."""
    print("\n4. Testing YAML file loading...")
    from agents.config.config_loader import load_agent_settings

    yaml_content = """
mode: paper
environment: dev
redis:
  url: redis://yamlhost:6379
  socket_timeout: 10.0
kraken:
  api_url: https://yaml.kraken.com
risk:
  max_leverage: 3.0
scalper:
  max_toxicity_score: 0.5
"""

    with NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        yaml_path = Path(f.name)

    try:
        settings = load_agent_settings(file=yaml_path)

        assert settings.environment == "dev"
        assert settings.redis.url == "redis://yamlhost:6379"
        assert settings.redis.socket_timeout == 10.0
        assert settings.kraken.api_url == "https://yaml.kraken.com"
        assert settings.risk.max_leverage == 3.0
        assert settings.scalper.max_toxicity_score == 0.5

        print("   PASS: YAML loading working")
        print(f"   - environment: {settings.environment}")
        print(f"   - redis.socket_timeout: {settings.redis.socket_timeout}")
    finally:
        yaml_path.unlink()


def test_precedence():
    """Test precedence: ENV > YAML > defaults."""
    print("\n5. Testing precedence (ENV > YAML > defaults)...")
    from agents.config.config_loader import load_agent_settings

    yaml_content = """
redis:
  url: redis://yamlhost:6379
  socket_timeout: 10.0
risk:
  max_leverage: 3.0
"""

    with NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write(yaml_content)
        yaml_path = Path(f.name)

    try:
        env = {
            "REDIS_URL": "redis://envhost:6379",  # Override YAML
            # socket_timeout should come from YAML
            # max_leverage should come from YAML
        }

        settings = load_agent_settings(env=env, file=yaml_path)

        # ENV wins
        assert settings.redis.url == "redis://envhost:6379"
        # YAML wins (no env override)
        assert settings.redis.socket_timeout == 10.0
        assert settings.risk.max_leverage == 3.0
        # Default wins (not in YAML or ENV)
        assert settings.redis.decode_responses is False

        print("   PASS: Precedence working correctly")
        print(f"   - redis.url: {settings.redis.url} (from ENV)")
        print(f"   - redis.socket_timeout: {settings.redis.socket_timeout} (from YAML)")
        print(f"   - redis.decode_responses: {settings.redis.decode_responses} (default)")
    finally:
        yaml_path.unlink()


def test_live_mode_validation():
    """Test live mode requires confirmation."""
    print("\n6. Testing live mode validation...")
    from agents.config.config_loader import load_agent_settings

    # Test 1: Live mode without confirmation should fail
    env = {
        "MODE": "live",
        "KRAKEN_API_KEY": "test_key",
        "KRAKEN_API_SECRET": "test_secret",
    }

    try:
        settings = load_agent_settings(env=env)
        print("   FAIL: Should have raised ValueError for missing confirmation")
        assert False
    except ValueError as e:
        assert "LIVE_TRADING_CONFIRMATION" in str(e)
        print("   PASS: Correctly rejected live mode without confirmation")

    # Test 2: Live mode with wrong confirmation should fail
    env["LIVE_TRADING_CONFIRMATION"] = "wrong-confirmation"
    try:
        settings = load_agent_settings(env=env)
        print("   FAIL: Should have raised ValueError for wrong confirmation")
        assert False
    except ValueError as e:
        assert "I-accept-the-risk" in str(e)
        print("   PASS: Correctly rejected wrong confirmation string")

    # Test 3: Live mode without credentials should fail
    env["LIVE_TRADING_CONFIRMATION"] = "I-accept-the-risk"
    env.pop("KRAKEN_API_KEY")
    try:
        settings = load_agent_settings(env=env)
        print("   FAIL: Should have raised ValueError for missing credentials")
        assert False
    except ValueError as e:
        assert "credentials" in str(e).lower()
        print("   PASS: Correctly rejected live mode without credentials")

    # Test 4: Live mode with all requirements should succeed
    env["KRAKEN_API_KEY"] = "test_key"
    env["KRAKEN_API_SECRET"] = "test_secret"
    env["LIVE_TRADING_CONFIRMATION"] = "I-accept-the-risk"

    settings = load_agent_settings(env=env)
    assert settings.mode == "live"
    print("   PASS: Accepted live mode with all requirements")


def test_redis_kwargs():
    """Test to_redis_kwargs() method."""
    print("\n7. Testing to_redis_kwargs() method...")
    from agents.config.config_loader import load_agent_settings

    # Test without TLS
    env = {
        "REDIS_URL": "redis://localhost:6379",
        "REDIS_SOCKET_TIMEOUT": "7.5",
    }

    settings = load_agent_settings(env=env)
    kwargs = settings.redis.to_redis_kwargs()

    assert kwargs["socket_timeout"] == 7.5
    assert kwargs["socket_connect_timeout"] == 5.0  # default
    assert "ssl_context" not in kwargs

    print("   PASS: Redis kwargs without TLS")
    print(f"   - socket_timeout: {kwargs['socket_timeout']}")

    # Test with TLS (should raise FileNotFoundError for missing cert)
    env["REDIS_URL"] = "rediss://secure.redis.com:6379"
    env["REDIS_CA_CERT_PATH"] = "/path/to/nonexistent/ca.crt"

    settings = load_agent_settings(env=env)

    try:
        kwargs = settings.redis.to_redis_kwargs()
        print("   FAIL: Should have raised FileNotFoundError for missing cert")
        assert False
    except FileNotFoundError as e:
        assert "CA certificate not found" in str(e)
        print("   PASS: Redis kwargs with TLS correctly validates cert existence")


def test_unit_test_override():
    """Test that unit tests can easily override settings."""
    print("\n8. Testing unit test override capability...")
    from agents.config.config_loader import load_agent_settings, Settings, RedisSettings

    # Method 1: Override via env dict
    test_env = {
        "MODE": "paper",
        "REDIS_URL": "redis://testhost:6379",
    }
    settings = load_agent_settings(env=test_env)
    assert settings.redis.url == "redis://testhost:6379"
    print("   PASS: Method 1 - Override via env dict")

    # Method 2: Create Settings directly
    settings = Settings(
        mode="paper",
        redis=RedisSettings(url="redis://directhost:6379"),
    )
    assert settings.redis.url == "redis://directhost:6379"
    print("   PASS: Method 2 - Create Settings directly")

    # Method 3: Modify after creation
    settings = load_agent_settings(env={"MODE": "paper"})
    # Note: Pydantic models are immutable by default, but you can use model_copy
    modified = settings.model_copy(update={"environment": "test"})
    assert modified.environment == "test"
    print("   PASS: Method 3 - Use model_copy for modifications")


def test_invalid_mode():
    """Test invalid mode rejection."""
    print("\n9. Testing invalid mode rejection...")
    from agents.config.config_loader import load_agent_settings

    env = {"MODE": "invalid"}

    try:
        settings = load_agent_settings(env=env)
        print("   FAIL: Should have raised ValueError for invalid mode")
        assert False
    except ValueError as e:
        assert "paper" in str(e) and "live" in str(e)
        print("   PASS: Correctly rejected invalid mode")


def main():
    """Run all tests."""
    print("="*60)
    print("Configuration Loader Tests")
    print("="*60)

    try:
        test_basic_import()
        test_default_settings()
        test_env_override()
        test_yaml_loading()
        test_precedence()
        test_live_mode_validation()
        test_redis_kwargs()
        test_unit_test_override()
        test_invalid_mode()

        print("\n" + "="*60)
        print("ALL TESTS PASSED")
        print("="*60)
        print("\nSummary:")
        print("- Pydantic v2 models working correctly")
        print("- load_agent_settings() supports ENV and YAML")
        print("- Precedence: ENV > YAML > defaults")
        print("- Live mode validation enforced")
        print("- to_redis_kwargs() provides Redis TLS support")
        print("- Unit tests can easily override settings")
        return 0

    except Exception as e:
        print(f"\n\nTEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
