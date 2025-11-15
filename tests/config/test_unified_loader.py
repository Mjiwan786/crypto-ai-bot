"""
D1 — Unit tests for unified_config_loader.py (C1)

Tests:
- Precedence: overrides > ENV > YAML > defaults
- LIVE mode guard (requires confirmation)
- Type coercion (bool/int/Decimal/list)
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Dict

import pytest
import yaml

from config.unified_config_loader import (
    load_settings,
    Settings,
    coerce_bool,
    coerce_int,
    coerce_decimal,
    coerce_list,
)


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def temp_yaml(tmp_path: Path) -> Path:
    """Create temporary YAML file for testing."""
    yaml_file = tmp_path / "test_settings.yaml"
    config = {
        "redis": {
            "url": "redis://yaml-host:6379",
            "max_connections": 15,
        },
        "kraken": {
            "sandbox": True,
        },
        "logging": {
            "level": "INFO",
        },
    }

    with open(yaml_file, 'w') as f:
        yaml.dump(config, f)

    return yaml_file


@pytest.fixture
def temp_override_yaml(tmp_path: Path) -> Path:
    """Create temporary override YAML file."""
    yaml_file = tmp_path / "override.yaml"
    config = {
        "redis": {
            "url": "redis://override-host:6379",
        },
        "logging": {
            "level": "DEBUG",
        },
    }

    with open(yaml_file, 'w') as f:
        yaml.dump(config, f)

    return yaml_file


# =============================================================================
# TESTS: Precedence (overrides > ENV > YAML > defaults)
# =============================================================================


def test_defaults_only():
    """Test loading with defaults only."""
    settings = load_settings(env={}, yaml_paths=[], overrides=None)

    assert settings.trading_mode.mode == "PAPER"
    assert settings.redis.url == "redis://localhost:6379"
    assert settings.kraken.sandbox is True


def test_yaml_overrides_defaults(temp_yaml: Path):
    """Test that YAML overrides defaults."""
    settings = load_settings(env={}, yaml_paths=[temp_yaml], overrides=None)

    # YAML value should override default
    assert settings.redis.url == "redis://yaml-host:6379"
    assert settings.redis.max_connections == 15


def test_env_overrides_yaml(temp_yaml: Path):
    """Test that ENV overrides YAML."""
    env = {
        "REDIS_URL": "redis://env-host:6379",
    }

    settings = load_settings(env=env, yaml_paths=[temp_yaml], overrides=None)

    # ENV should win over YAML
    assert settings.redis.url == "redis://env-host:6379"


def test_overrides_trump_env(temp_yaml: Path):
    """Test that overrides trump ENV."""
    env = {
        "REDIS_URL": "redis://env-host:6379",
    }

    overrides = {
        "redis": {
            "url": "redis://override-host:6379",
        }
    }

    settings = load_settings(env=env, yaml_paths=[temp_yaml], overrides=overrides)

    # Override should win over everything
    assert settings.redis.url == "redis://override-host:6379"


def test_yaml_left_to_right_precedence(temp_yaml: Path, temp_override_yaml: Path):
    """Test that YAML files have left→right precedence."""
    settings = load_settings(
        env={},
        yaml_paths=[temp_yaml, temp_override_yaml],
        overrides=None
    )

    # Right (override.yaml) should win
    assert settings.redis.url == "redis://override-host:6379"
    assert settings.logging.level == "DEBUG"


def test_full_precedence_chain(temp_yaml: Path):
    """Test complete precedence chain."""
    # YAML sets redis.url = yaml-host
    # ENV sets redis.url = env-host
    # Override sets redis.url = override-host

    env = {
        "REDIS_URL": "redis://env-host:6379",
    }

    overrides = {
        "redis": {
            "url": "redis://override-host:6379",
        }
    }

    settings = load_settings(env=env, yaml_paths=[temp_yaml], overrides=overrides)

    # Override should win (highest precedence)
    assert settings.redis.url == "redis://override-host:6379"


# =============================================================================
# TESTS: LIVE Mode Guard
# =============================================================================


def test_live_mode_without_confirmation_fails():
    """Test that LIVE mode without confirmation raises error."""
    overrides = {
        "trading_mode": {
            "mode": "LIVE",
        }
    }

    with pytest.raises(ValueError) as exc_info:
        load_settings(env={}, yaml_paths=[], overrides=overrides)

    assert "YES_I_WANT_LIVE_TRADING" in str(exc_info.value)


def test_live_mode_with_confirmation_succeeds():
    """Test that LIVE mode with confirmation succeeds."""
    overrides = {
        "trading_mode": {
            "mode": "LIVE",
            "live_confirmation": "YES_I_WANT_LIVE_TRADING",
        }
    }

    settings = load_settings(env={}, yaml_paths=[], overrides=overrides)

    assert settings.trading_mode.mode == "LIVE"


def test_live_mode_env_confirmation():
    """Test LIVE mode with ENV confirmation."""
    env = {
        "TRADING_MODE": "LIVE",
        "LIVE_CONFIRMATION": "YES_I_WANT_LIVE_TRADING",
    }

    settings = load_settings(env=env, yaml_paths=[], overrides=None)

    assert settings.trading_mode.mode == "LIVE"


def test_live_mode_wrong_confirmation_fails():
    """Test that wrong confirmation string fails."""
    overrides = {
        "trading_mode": {
            "mode": "LIVE",
            "live_confirmation": "YES",  # Wrong confirmation
        }
    }

    with pytest.raises(ValueError) as exc_info:
        load_settings(env={}, yaml_paths=[], overrides=overrides)

    assert "YES_I_WANT_LIVE_TRADING" in str(exc_info.value)


# =============================================================================
# TESTS: Type Coercion
# =============================================================================


def test_coerce_bool_from_string():
    """Test boolean coercion from strings."""
    assert coerce_bool("true") is True
    assert coerce_bool("True") is True
    assert coerce_bool("1") is True
    assert coerce_bool("yes") is True
    assert coerce_bool("on") is True

    assert coerce_bool("false") is False
    assert coerce_bool("False") is False
    assert coerce_bool("0") is False
    assert coerce_bool("no") is False
    assert coerce_bool("off") is False


def test_coerce_int_from_string():
    """Test integer coercion from strings."""
    assert coerce_int("10") == 10
    assert coerce_int("100") == 100
    assert coerce_int(10) == 10  # Already int


def test_coerce_decimal_from_string():
    """Test Decimal coercion from strings."""
    assert coerce_decimal("0.5") == Decimal("0.5")
    assert coerce_decimal("1.25") == Decimal("1.25")
    assert coerce_decimal(0.5) == Decimal("0.5")


def test_coerce_list_from_string():
    """Test list coercion from comma-separated string."""
    assert coerce_list("BTCUSDT,ETHUSDT,SOLUSDT") == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert coerce_list("A, B, C") == ["A", "B", "C"]  # Strips whitespace


def test_env_type_coercion_applied():
    """Test that type coercion is applied to ENV variables."""
    env = {
        "REDIS_TLS": "true",
        "REDIS_MAX_CONNECTIONS": "20",
        "POSITION_SIZE_PCT": "0.75",
        "TRADING_PAIRS": "BTCUSDT,ETHUSDT",
    }

    settings = load_settings(env=env, yaml_paths=[], overrides=None)

    # Types should be coerced correctly
    assert settings.redis.tls is True  # bool
    assert settings.redis.max_connections == 20  # int
    assert settings.trading.position_size_pct == Decimal("0.75")  # Decimal
    assert settings.trading.pairs == ["BTCUSDT", "ETHUSDT"]  # list


# =============================================================================
# TESTS: TLS Auto-Detection
# =============================================================================


def test_tls_auto_detected_from_rediss_url():
    """Test that TLS is auto-detected from rediss:// URL."""
    env = {
        "REDIS_URL": "rediss://redis.example.com:6379",
    }

    settings = load_settings(env=env, yaml_paths=[], overrides=None)

    # TLS should be auto-enabled
    assert settings.redis.tls is True
    assert settings.redis.url == "rediss://redis.example.com:6379"


def test_redis_url_without_tls():
    """Test that redis:// URL doesn't auto-enable TLS."""
    env = {
        "REDIS_URL": "redis://redis.example.com:6379",
    }

    settings = load_settings(env=env, yaml_paths=[], overrides=None)

    # TLS should remain False
    assert settings.redis.tls is False


# =============================================================================
# TESTS: Settings Schema Validation
# =============================================================================


def test_settings_frozen():
    """Test that Settings instances are frozen (immutable)."""
    settings = load_settings(env={}, yaml_paths=[], overrides=None)

    # Attempt to modify should raise error
    with pytest.raises(Exception):  # Pydantic ValidationError
        settings.redis.url = "modified"


def test_settings_extra_forbid():
    """Test that Settings rejects extra fields."""
    with pytest.raises(Exception):  # Pydantic ValidationError
        Settings(extra_field="should_fail")


def test_invalid_redis_url_fails():
    """Test that invalid Redis URL raises validation error."""
    overrides = {
        "redis": {
            "url": "http://invalid",  # Not redis:// or rediss://
        }
    }

    with pytest.raises(ValueError) as exc_info:
        load_settings(env={}, yaml_paths=[], overrides=overrides)

    assert "redis://" in str(exc_info.value) or "rediss://" in str(exc_info.value)


def test_invalid_log_level_fails():
    """Test that invalid log level raises validation error."""
    overrides = {
        "logging": {
            "level": "INVALID",
        }
    }

    with pytest.raises(ValueError) as exc_info:
        load_settings(env={}, yaml_paths=[], overrides=overrides)

    assert "level" in str(exc_info.value).lower()


# =============================================================================
# TESTS: ENV Mapping
# =============================================================================


def test_all_env_mappings_work():
    """Test that all documented ENV mappings work."""
    env = {
        # Redis
        "REDIS_URL": "redis://test:6379",
        "REDIS_TLS": "false",
        "REDIS_MAX_CONNECTIONS": "25",

        # Kraken
        "KRAKEN_API_KEY": "test-key",
        "KRAKEN_API_SECRET": "test-secret",
        "KRAKEN_SANDBOX": "true",

        # Trading mode
        "TRADING_MODE": "PAPER",

        # Streams
        "STREAM_PREFIX": "test",

        # Logging
        "LOG_LEVEL": "DEBUG",

        # Trading
        "TRADING_PAIRS": "BTCUSDT,ETHUSDT",
        "POSITION_SIZE_PCT": "0.6",
    }

    settings = load_settings(env=env, yaml_paths=[], overrides=None)

    # Verify all mappings applied
    assert settings.redis.url == "redis://test:6379"
    assert settings.redis.max_connections == 25
    assert settings.kraken.api_key == "test-key"
    assert settings.kraken.sandbox is True
    assert settings.trading_mode.mode == "PAPER"
    assert settings.streams.prefix == "test"
    assert settings.logging.level == "DEBUG"
    assert settings.trading.pairs == ["BTCUSDT", "ETHUSDT"]
    assert settings.trading.position_size_pct == Decimal("0.6")


# =============================================================================
# TESTS: Deep Merge
# =============================================================================


def test_deep_merge_nested_dicts():
    """Test that nested dictionaries are deep merged."""
    overrides1 = {
        "redis": {
            "url": "redis://host1:6379",
            "max_connections": 10,
        }
    }

    overrides2 = {
        "redis": {
            "max_connections": 20,  # Override just this field
        }
    }

    settings = load_settings(
        env={},
        yaml_paths=[],
        overrides=overrides1,
    )

    # Then apply second override (simulating precedence)
    from config.unified_config_loader import _merge_dicts
    merged = _merge_dicts(overrides1, overrides2)

    # Should have merged nested values
    assert merged["redis"]["url"] == "redis://host1:6379"  # From overrides1
    assert merged["redis"]["max_connections"] == 20  # From overrides2


# =============================================================================
# TESTS: Error Handling
# =============================================================================


def test_file_not_found_error():
    """Test that missing YAML file raises FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_settings(
            env={},
            yaml_paths=[Path("/nonexistent/config.yaml")],
            overrides=None
        )


def test_invalid_yaml_syntax(tmp_path: Path):
    """Test that invalid YAML raises YAMLError."""
    invalid_yaml = tmp_path / "invalid.yaml"
    with open(invalid_yaml, 'w') as f:
        f.write("invalid: yaml: syntax: [unclosed")

    with pytest.raises(yaml.YAMLError):
        load_settings(env={}, yaml_paths=[invalid_yaml], overrides=None)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
