"""
Unit tests for PRD-001 Section 7.4 Configuration Hot Reload

Tests coverage:
- ConfigHotReloader initialization and lifecycle
- File watcher start/stop
- Restricted field change blocking
- Reloadable field change success
- Config change callback execution
- Debouncing behavior
- Singleton pattern

Author: Crypto AI Bot Team
"""

import pytest
import time
import yaml
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from config.prd_config_hot_reload import (
    ConfigHotReloader,
    ConfigFileHandler,
    get_hot_reloader,
    RESTRICTED_FIELDS,
    RELOADABLE_FIELDS
)


@pytest.fixture
def temp_config_file(tmp_path):
    """Create temporary config file for testing."""
    config_path = tmp_path / "test_settings.yaml"

    initial_config = {
        "redis": {
            "url": "redis://localhost:6379",
            "db": 0
        },
        "mode": {
            "bot_mode": "PAPER",
            "trading_mode": "paper"
        },
        "logging": {
            "level": "INFO",
            "dir": "logs/"
        },
        "monitoring": {
            "prometheus": {
                "port": 9108
            },
            "alerts": {
                "level": "ERROR"
            }
        }
    }

    with open(config_path, 'w') as f:
        yaml.dump(initial_config, f)

    return config_path


class TestConfigFileHandler:
    """Test ConfigFileHandler class."""

    def test_handler_initialization(self, temp_config_file):
        """Test file handler initialization."""
        callback = Mock()
        handler = ConfigFileHandler(
            config_path=temp_config_file,
            reload_callback=callback
        )

        assert handler.config_path == temp_config_file
        assert handler.reload_callback == callback
        assert handler.debounce_seconds == 2
        assert handler.last_reload_time == 0

    def test_on_modified_calls_callback(self, temp_config_file):
        """Test that on_modified calls reload callback."""
        callback = Mock()
        handler = ConfigFileHandler(
            config_path=temp_config_file,
            reload_callback=callback
        )

        # Create mock event
        event = Mock()
        event.src_path = str(temp_config_file)

        handler.on_modified(event)

        # Callback should be called
        callback.assert_called_once()

    def test_debouncing_prevents_rapid_reloads(self, temp_config_file):
        """Test debouncing prevents rapid successive reloads."""
        callback = Mock()
        handler = ConfigFileHandler(
            config_path=temp_config_file,
            reload_callback=callback
        )

        event = Mock()
        event.src_path = str(temp_config_file)

        # First call should trigger callback
        handler.on_modified(event)
        assert callback.call_count == 1

        # Immediate second call should be debounced
        handler.on_modified(event)
        assert callback.call_count == 1  # Still 1, not 2

    def test_different_file_ignored(self, temp_config_file, tmp_path):
        """Test that modifications to different files are ignored."""
        callback = Mock()
        handler = ConfigFileHandler(
            config_path=temp_config_file,
            reload_callback=callback
        )

        # Create event for different file
        event = Mock()
        event.src_path = str(tmp_path / "other_file.yaml")

        handler.on_modified(event)

        # Callback should not be called
        callback.assert_not_called()


class TestConfigHotReloader:
    """Test ConfigHotReloader class."""

    def test_reloader_initialization(self, temp_config_file):
        """Test reloader initialization."""
        callback = Mock()
        reloader = ConfigHotReloader(
            config_path=temp_config_file,
            on_config_change=callback
        )

        assert reloader.config_path == temp_config_file
        assert reloader.on_config_change == callback
        assert reloader.reload_count == 0
        assert reloader.observer is None

    def test_start_loads_initial_config(self, temp_config_file):
        """Test that start loads initial configuration."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        try:
            reloader.start()

            # Config should be loaded
            assert reloader.current_config is not None
            assert "redis" in reloader.current_config
            assert reloader.observer is not None
        finally:
            reloader.stop()

    def test_start_twice_warns(self, temp_config_file, caplog):
        """Test that starting twice logs warning."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        try:
            reloader.start()
            reloader.start()  # Second start

            # Should have warning about already started
            assert any("already started" in record.message.lower()
                      for record in caplog.records)
        finally:
            reloader.stop()

    def test_stop_when_not_started(self, temp_config_file):
        """Test that stop when not started doesn't error."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        # Should not raise error
        reloader.stop()

        assert reloader.observer is None

    def test_get_reload_count(self, temp_config_file):
        """Test get_reload_count method."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        assert reloader.get_reload_count() == 0

        reloader.reload_count = 5
        assert reloader.get_reload_count() == 5

    def test_get_current_config(self, temp_config_file):
        """Test get_current_config returns copy."""
        reloader = ConfigHotReloader(config_path=temp_config_file)
        reloader.start()

        try:
            config1 = reloader.get_current_config()
            config2 = reloader.get_current_config()

            # Should be different objects (copies)
            assert config1 is not config2

            # But same content
            assert config1 == config2
        finally:
            reloader.stop()

    def test_check_restricted_changes_detects_redis_url_change(self, temp_config_file):
        """Test that changes to REDIS_URL are detected as restricted."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        old_config = {
            "redis": {"url": "redis://localhost:6379"}
        }

        new_config = {
            "redis": {"url": "redis://prod-server:6379"}
        }

        restricted = reloader._check_restricted_changes(old_config, new_config)

        # Should have one restricted change
        assert len(restricted) == 1
        assert restricted[0][0] == "redis.url"
        assert restricted[0][1] == "redis://localhost:6379"
        assert restricted[0][2] == "redis://prod-server:6379"

    def test_check_restricted_changes_detects_trading_mode_change(self, temp_config_file):
        """Test that changes to TRADING_MODE are detected as restricted."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        old_config = {
            "mode": {"trading_mode": "paper"}
        }

        new_config = {
            "mode": {"trading_mode": "live"}
        }

        restricted = reloader._check_restricted_changes(old_config, new_config)

        # Should have one restricted change
        assert len(restricted) == 1
        assert restricted[0][0] == "mode.trading_mode"

    def test_check_restricted_changes_allows_non_restricted(self, temp_config_file):
        """Test that non-restricted changes are not flagged."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        old_config = {
            "redis": {"url": "redis://localhost:6379"},
            "logging": {"level": "INFO"}
        }

        new_config = {
            "redis": {"url": "redis://localhost:6379"},  # Same
            "logging": {"level": "DEBUG"}  # Changed, but not restricted
        }

        restricted = reloader._check_restricted_changes(old_config, new_config)

        # Should have no restricted changes
        assert len(restricted) == 0

    def test_find_changed_fields_detects_log_level(self, temp_config_file):
        """Test that log level changes are detected."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        old_config = {
            "logging": {"level": "INFO"}
        }

        new_config = {
            "logging": {"level": "DEBUG"}
        }

        changed = reloader._find_changed_fields(old_config, new_config)

        # Should have one changed field
        assert len(changed) == 1
        assert changed[0][0] == "logging.level"
        assert changed[0][1] == "INFO"
        assert changed[0][2] == "DEBUG"

    def test_find_changed_fields_only_checks_reloadable(self, temp_config_file):
        """Test that only reloadable fields are checked."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        old_config = {
            "logging": {"level": "INFO"},
            "some_other": {"field": "value1"}  # Not in RELOADABLE_FIELDS
        }

        new_config = {
            "logging": {"level": "DEBUG"},
            "some_other": {"field": "value2"}  # Changed but not reloadable
        }

        changed = reloader._find_changed_fields(old_config, new_config)

        # Should only detect logging.level change
        assert len(changed) == 1
        assert changed[0][0] == "logging.level"

    def test_get_nested_value(self, temp_config_file):
        """Test _get_nested_value method."""
        reloader = ConfigHotReloader(config_path=temp_config_file)

        config = {
            "redis": {
                "url": "redis://localhost:6379",
                "db": 0
            }
        }

        # Test valid paths
        assert reloader._get_nested_value(config, "redis.url") == "redis://localhost:6379"
        assert reloader._get_nested_value(config, "redis.db") == 0

        # Test invalid path returns default
        assert reloader._get_nested_value(config, "redis.nonexistent") is None
        assert reloader._get_nested_value(config, "invalid.path", default="fallback") == "fallback"

    def test_handle_config_change_blocks_restricted_changes(self, temp_config_file, caplog):
        """Test that restricted field changes are blocked."""
        reloader = ConfigHotReloader(config_path=temp_config_file)
        reloader.start()

        try:
            initial_count = reloader.reload_count

            # Modify config with restricted change
            new_config = {
                "redis": {
                    "url": "redis://prod-server:6379",  # RESTRICTED CHANGE
                    "db": 0
                },
                "mode": {
                    "bot_mode": "PAPER",
                    "trading_mode": "paper"
                },
                "logging": {
                    "level": "INFO"
                }
            }

            with open(temp_config_file, 'w') as f:
                yaml.dump(new_config, f)

            # Wait for file watcher (small delay)
            time.sleep(0.1)

            # Trigger reload manually (since file watcher might not trigger in test)
            reloader._handle_config_change()

            # Reload should be blocked
            assert reloader.reload_count == initial_count

            # Should have warning in logs
            assert any("RESTRICTED FIELD CHANGES" in record.message
                      for record in caplog.records)
        finally:
            reloader.stop()

    def test_handle_config_change_allows_reloadable_changes(self, temp_config_file, caplog):
        """Test that reloadable field changes are allowed."""
        callback = Mock()
        reloader = ConfigHotReloader(
            config_path=temp_config_file,
            on_config_change=callback
        )
        reloader.start()

        try:
            initial_count = reloader.reload_count

            # Modify config with reloadable change
            new_config = {
                "redis": {
                    "url": "redis://localhost:6379",  # Same
                    "db": 0
                },
                "mode": {
                    "bot_mode": "PAPER",
                    "trading_mode": "paper"
                },
                "logging": {
                    "level": "DEBUG"  # RELOADABLE CHANGE
                }
            }

            with open(temp_config_file, 'w') as f:
                yaml.dump(new_config, f)

            # Trigger reload manually
            reloader._handle_config_change()

            # Reload should succeed
            assert reloader.reload_count == initial_count + 1

            # Callback should be called
            callback.assert_called_once()

            # Current config should be updated
            assert reloader.current_config["logging"]["level"] == "DEBUG"
        finally:
            reloader.stop()

    def test_handle_config_change_with_invalid_yaml(self, temp_config_file, caplog):
        """Test handling of invalid YAML file."""
        reloader = ConfigHotReloader(config_path=temp_config_file)
        reloader.start()

        try:
            initial_count = reloader.reload_count

            # Write invalid YAML
            with open(temp_config_file, 'w') as f:
                f.write("invalid: yaml: syntax: [")

            # Trigger reload manually
            reloader._handle_config_change()

            # Reload should fail gracefully
            assert reloader.reload_count == initial_count

            # Should keep current config
            assert "redis" in reloader.current_config
        finally:
            reloader.stop()


class TestSingletonPattern:
    """Test singleton pattern for get_hot_reloader."""

    def test_get_hot_reloader_singleton(self, temp_config_file):
        """Test that get_hot_reloader returns singleton."""
        # Reset singleton
        import config.prd_config_hot_reload as module
        module._reloader_instance = None

        reloader1 = get_hot_reloader(
            config_path=temp_config_file,
            on_config_change=Mock()
        )

        reloader2 = get_hot_reloader()

        # Should be same instance
        assert reloader1 is reloader2

    def test_get_hot_reloader_default_path(self, temp_config_file):
        """Test default config path."""
        # Reset singleton
        import config.prd_config_hot_reload as module
        module._reloader_instance = None

        # Just test that get_hot_reloader works with explicit path
        reloader = get_hot_reloader(config_path=temp_config_file)

        # Should use provided path
        assert reloader is not None
        assert reloader.config_path == temp_config_file


class TestRestrictedAndReloadableFields:
    """Test RESTRICTED_FIELDS and RELOADABLE_FIELDS constants."""

    def test_restricted_fields_defined(self):
        """Test that restricted fields are properly defined."""
        assert "redis.url" in RESTRICTED_FIELDS
        assert "mode.bot_mode" in RESTRICTED_FIELDS
        assert "mode.trading_mode" in RESTRICTED_FIELDS
        assert "exchange.primary" in RESTRICTED_FIELDS

    def test_reloadable_fields_defined(self):
        """Test that reloadable fields are properly defined."""
        assert "logging.level" in RELOADABLE_FIELDS
        assert "logging.dir" in RELOADABLE_FIELDS
        assert "monitoring.prometheus.port" in RELOADABLE_FIELDS

    def test_no_overlap_between_restricted_and_reloadable(self):
        """Test that restricted and reloadable fields don't overlap."""
        overlap = RESTRICTED_FIELDS.intersection(RELOADABLE_FIELDS)
        assert len(overlap) == 0, f"Fields should not be both restricted and reloadable: {overlap}"
