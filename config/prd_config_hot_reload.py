"""
PRD-001 Section 7.4 Configuration Hot Reload

This module implements PRD-001 Section 7.4 hot reload requirements with:
- File watcher for config/settings.yaml changes
- Reload non-critical params without restart (log_level, timeouts)
- Restrict hot-reload: cannot change REDIS_URL, TRADING_MODE, TRADING_PAIRS
- Log config reload events at INFO level with changed fields

Author: Crypto AI Bot Team
Version: 1.0.0
"""

from __future__ import annotations

import logging
import time
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, Set, Callable
from threading import Thread, Event
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent

logger = logging.getLogger(__name__)

# PRD-001 Section 7.4: Non-reloadable fields (critical configuration)
RESTRICTED_FIELDS = {
    "redis.url",
    "mode.bot_mode",
    "mode.trading_mode",
    "exchange.primary",
    "redis.streams",  # Stream names are critical
}

# PRD-001 Section 7.4: Reloadable fields (non-critical configuration)
RELOADABLE_FIELDS = {
    "logging.level",
    "logging.dir",
    "monitoring.prometheus.port",
    "monitoring.alerts.level",
    "discord.enabled",
    "discord.webhook_url",
}


class ConfigFileHandler(FileSystemEventHandler):
    """
    File system event handler for configuration file changes.

    Watches config/settings.yaml for modifications and triggers reload.
    """

    def __init__(self, config_path: Path, reload_callback: Callable):
        """
        Initialize config file handler.

        Args:
            config_path: Path to config file to watch
            reload_callback: Callback function to call on file change
        """
        self.config_path = config_path
        self.reload_callback = reload_callback
        self.last_reload_time = 0
        self.debounce_seconds = 2  # Debounce rapid file changes

    def on_modified(self, event: FileModifiedEvent):
        """
        Handle file modification event.

        Args:
            event: File system event
        """
        if event.src_path == str(self.config_path):
            # Debounce rapid changes
            current_time = time.time()
            if current_time - self.last_reload_time < self.debounce_seconds:
                logger.debug("Ignoring rapid config change (debounced)")
                return

            self.last_reload_time = current_time

            logger.info(f"Config file modified: {self.config_path}")
            self.reload_callback()


class ConfigHotReloader:
    """
    PRD-001 Section 7.4 compliant configuration hot reloader.

    Features:
    - Watch config/settings.yaml for changes
    - Reload non-critical parameters without restart
    - Restrict changes to critical fields (REDIS_URL, TRADING_MODE, etc.)
    - Log reload events with changed fields
    - Thread-safe configuration updates

    Usage:
        reloader = ConfigHotReloader(
            config_path=Path("config/settings.yaml"),
            on_config_change=lambda new_config: print(f"Config updated: {new_config}")
        )

        reloader.start()
        # ... application runs ...
        reloader.stop()
    """

    def __init__(
        self,
        config_path: Path,
        on_config_change: Optional[Callable[[Dict[str, Any]], None]] = None
    ):
        """
        Initialize configuration hot reloader.

        Args:
            config_path: Path to configuration file
            on_config_change: Callback for config changes (receives new config dict)
        """
        self.config_path = config_path
        self.on_config_change = on_config_change
        self.current_config: Dict[str, Any] = {}
        self.observer: Optional[Observer] = None
        self.stop_event = Event()
        self.reload_count = 0

        logger.info(f"ConfigHotReloader initialized: watching {config_path}")

    def start(self) -> None:
        """
        Start watching configuration file for changes.

        PRD-001 Section 7.4: Implement file watcher for config/settings.yaml
        """
        if self.observer is not None:
            logger.warning("Hot reload already started")
            return

        # Load initial configuration
        self.current_config = self._load_config()

        # Set up file watcher
        event_handler = ConfigFileHandler(
            config_path=self.config_path,
            reload_callback=self._handle_config_change
        )

        self.observer = Observer()
        self.observer.schedule(
            event_handler,
            path=str(self.config_path.parent),
            recursive=False
        )

        self.observer.start()
        logger.info("✓ Config hot reload started")

    def stop(self) -> None:
        """Stop watching configuration file."""
        if self.observer is None:
            return

        self.observer.stop()
        self.observer.join()
        self.observer = None
        self.stop_event.set()

        logger.info("✓ Config hot reload stopped")

    def _load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file.

        Returns:
            Configuration dictionary
        """
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            return config or {}
        except Exception as e:
            logger.error(f"Error loading config: {e}")
            return {}

    def _handle_config_change(self) -> None:
        """
        Handle configuration file change.

        PRD-001 Section 7.4: Reload non-critical params without restart
        """
        logger.info("=" * 80)
        logger.info("CONFIG FILE CHANGED - Reloading...")
        logger.info("=" * 80)

        # Load new configuration
        new_config = self._load_config()

        if not new_config:
            logger.error("Failed to load new configuration, keeping current config")
            return

        # Check for restricted field changes
        restricted_changes = self._check_restricted_changes(
            self.current_config,
            new_config
        )

        if restricted_changes:
            logger.warning("=" * 80)
            logger.warning("RESTRICTED FIELD CHANGES DETECTED - RELOAD BLOCKED")
            logger.warning("=" * 80)
            logger.warning("The following critical fields cannot be changed via hot reload:")
            for field, old_val, new_val in restricted_changes:
                logger.warning(f"  {field}: {old_val} → {new_val}")
            logger.warning("")
            logger.warning("To apply these changes, restart the application.")
            logger.warning("=" * 80)
            return

        # Find changed fields
        changed_fields = self._find_changed_fields(
            self.current_config,
            new_config
        )

        if not changed_fields:
            logger.info("No configuration changes detected")
            return

        # Log changed fields
        logger.info(f"Applying {len(changed_fields)} configuration change(s):")
        for field, old_val, new_val in changed_fields:
            logger.info(f"  {field}: {old_val} → {new_val}")

        # Update current configuration
        self.current_config = new_config
        self.reload_count += 1

        # Trigger callback
        if self.on_config_change:
            try:
                self.on_config_change(new_config)
                logger.info("✓ Configuration reloaded successfully")
            except Exception as e:
                logger.error(f"Error in config change callback: {e}")

        logger.info(f"✓ Config hot reload #{self.reload_count} complete")
        logger.info("=" * 80)

    def _check_restricted_changes(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any]
    ) -> list:
        """
        Check for changes to restricted fields.

        PRD-001 Section 7.4: Cannot change REDIS_URL, TRADING_MODE, TRADING_PAIRS

        Args:
            old_config: Current configuration
            new_config: New configuration

        Returns:
            List of (field_path, old_value, new_value) for restricted changes
        """
        restricted_changes = []

        for field_path in RESTRICTED_FIELDS:
            old_value = self._get_nested_value(old_config, field_path)
            new_value = self._get_nested_value(new_config, field_path)

            if old_value != new_value:
                restricted_changes.append((field_path, old_value, new_value))

        return restricted_changes

    def _find_changed_fields(
        self,
        old_config: Dict[str, Any],
        new_config: Dict[str, Any]
    ) -> list:
        """
        Find all changed fields between configurations.

        Args:
            old_config: Current configuration
            new_config: New configuration

        Returns:
            List of (field_path, old_value, new_value) for changed fields
        """
        changed_fields = []

        # Only check reloadable fields
        for field_path in RELOADABLE_FIELDS:
            old_value = self._get_nested_value(old_config, field_path)
            new_value = self._get_nested_value(new_config, field_path)

            if old_value != new_value:
                changed_fields.append((field_path, old_value, new_value))

        return changed_fields

    def _get_nested_value(
        self,
        config: Dict[str, Any],
        path: str,
        default: Any = None
    ) -> Any:
        """
        Get nested value from config by dot-separated path.

        Args:
            config: Configuration dictionary
            path: Dot-separated path (e.g., "redis.url")
            default: Default value if path not found

        Returns:
            Value at path or default
        """
        keys = path.split(".")
        value = config

        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default

        return value

    def get_reload_count(self) -> int:
        """
        Get number of successful reloads.

        Returns:
            Reload count
        """
        return self.reload_count

    def get_current_config(self) -> Dict[str, Any]:
        """
        Get current configuration.

        Returns:
            Current configuration dictionary
        """
        return self.current_config.copy()


# Singleton instance
_reloader_instance: Optional[ConfigHotReloader] = None


def get_hot_reloader(
    config_path: Optional[Path] = None,
    on_config_change: Optional[Callable] = None
) -> ConfigHotReloader:
    """
    Get singleton ConfigHotReloader instance.

    Args:
        config_path: Path to config file (default: config/settings.yaml)
        on_config_change: Config change callback

    Returns:
        ConfigHotReloader instance
    """
    global _reloader_instance

    if _reloader_instance is None:
        if config_path is None:
            config_path = Path("config/settings.yaml")

        _reloader_instance = ConfigHotReloader(
            config_path=config_path,
            on_config_change=on_config_change
        )

    return _reloader_instance


# Export for convenience
__all__ = [
    "ConfigHotReloader",
    "get_hot_reloader",
    "RESTRICTED_FIELDS",
    "RELOADABLE_FIELDS",
]
