# config/loader.py
"""
Enhanced production-grade configuration loader for crypto-ai-bot.

Adds:
- Singleton ConfigManager with thread safety
- Hot-reload via watchdog (auto) or polling fallback
- Versioning/history with deep-copy snapshots & rollback
- Runtime dot-path overrides (supports list indices, type coercion)
- Health state, change log, diffing, content-hash guard
- Safe Pydantic v1/v2 model (de)serialization helpers
- Clean module-level API surface compatible with existing imports
"""

from __future__ import annotations

import os
import yaml
import logging
import threading
import time
import hashlib
from pathlib import Path
from typing import Dict, List, Optional, Union, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
import json
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, Future
from copy import deepcopy

# ----------------------------
# Import base configuration system (your existing implementation)
# ----------------------------
try:
    from .config_loader import (
        CryptoAIBotConfig,
        ConfigLoader,
        ConfigValidator,
        load_and_validate_config,
        validate_deployment,
    )
except Exception:
    # fallback when executed as a script: python config/loader.py
    from config_loader import (  # type: ignore
        CryptoAIBotConfig,
        ConfigLoader,
        ConfigValidator,
        load_and_validate_config,
        validate_deployment,
    )

log = logging.getLogger("config.manager")
LOG_FMT = "%(asctime)s | %(levelname)s | %(message)s"


# ----------------------------
# Events & health structures
# ----------------------------
class ConfigEvent(str, Enum):
    LOADED = "loaded"
    UPDATED = "updated"
    VALIDATED = "validated"
    ERROR = "error"
    ROLLBACK = "rollback"


@dataclass
class ConfigChange:
    timestamp: datetime
    event: ConfigEvent
    version: str
    changes: Dict[str, Any] = field(default_factory=dict)
    error: Optional[Exception] = None
    rollback_available: bool = False


@dataclass
class ConfigHealth:
    status: str  # "healthy" | "degraded" | "error" | "unknown"
    last_update: datetime
    version: str
    validation_errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    file_exists: bool = True
    file_readable: bool = True
    syntax_valid: bool = True


# ----------------------------
# Config Manager (singleton)
# ----------------------------
class ConfigManager:
    """
    Enhanced configuration manager with singleton access, hot reload, versioning, rollback,
    runtime overrides, validation, and change notifications.
    """

    _instance: Optional["ConfigManager"] = None
    _class_lock = threading.RLock()

    def __init__(self, config_path: str = "config/settings.yaml"):
        if ConfigManager._instance is not None:
            raise RuntimeError("ConfigManager is a singleton. Use get_instance().")

        self.config_path = Path(config_path)
        self.config: Optional[CryptoAIBotConfig] = None
        self.config_loader = ConfigLoader(str(self.config_path))  # kept for parity

        # Versioning & history
        self.config_history: List[CryptoAIBotConfig] = []
        self.current_version = "1.0.0"
        self.max_history_size = 10

        # Event handlers
        self.event_handlers: Dict[ConfigEvent, List[Callable]] = {event: [] for event in ConfigEvent}

        # Health
        self.health = ConfigHealth(
            status="unknown",
            last_update=datetime.now(),
            version=self.current_version,
        )

        # Hot reload infra
        self.hot_reload_enabled = False
        self._watcher_executor: Optional[ThreadPoolExecutor] = None
        self.file_watcher_task: Optional[Future] = None
        self.last_file_mtime: Optional[float] = None
        self.last_file_hash: Optional[str] = None
        self._observer = None  # watchdog observer if available

        # Thread safety for updates
        self._update_lock = threading.RLock()

        # Change tracking
        self.change_log: List[ConfigChange] = []
        self.max_change_log_size = 100

        # Runtime overrides: "path.to.key" -> value
        self.runtime_overrides: Dict[str, Any] = {}

        # Init logging if parent app hasn’t
        if not logging.getLogger().handlers:
            logging.basicConfig(level=logging.INFO, format=LOG_FMT)

        log.info("ConfigManager starting with path: %s", self.config_path)
        self._load_initial_config()

    # ---- Singleton accessors ----
    @classmethod
    def get_instance(cls, config_path: str = "config/settings.yaml") -> "ConfigManager":
        if cls._instance is None:
            with cls._class_lock:
                if cls._instance is None:
                    cls._instance = cls(config_path)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._class_lock:
            if cls._instance:
                cls._instance.shutdown()
            cls._instance = None

    # ---- Internal helpers ----
    @staticmethod
    def _to_dict(model_obj: Any) -> Dict[str, Any]:
        """Pydantic v2/v1 safe conversion to dict."""
        if hasattr(model_obj, "model_dump"):          # v2
            return model_obj.model_dump(mode="json")
        if hasattr(model_obj, "dict"):                # v1
            return model_obj.dict()
        # Fallback: best-effort JSON conversion
        return json.loads(json.dumps(model_obj, default=str))

    @staticmethod
    def _file_sha256(path: Path) -> Optional[str]:
        try:
            h = hashlib.sha256()
            with path.open("rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _load_initial_config(self):
        """Load and validate configuration at startup."""
        try:
            with self._update_lock:
                cfg, validation_report = load_and_validate_config(str(self.config_path))

                # Health flags
                self.health.file_exists = self.config_path.exists()
                self.health.file_readable = True
                self.health.syntax_valid = True
                self.health.validation_errors = validation_report.get("strategy_issues", [])
                self.health.warnings = validation_report.get("performance_issues", [])
                self.health.status = "healthy" if validation_report.get("deployment_ready", False) else "degraded"
                self.health.last_update = datetime.now()

                self.config = cfg
                if self.config_path.exists():
                    self.last_file_mtime = self.config_path.stat().st_mtime
                    self.last_file_hash = self._file_sha256(self.config_path)

                change = ConfigChange(
                    timestamp=datetime.now(),
                    event=ConfigEvent.LOADED,
                    version=self.current_version,
                )
                self._record_change(change)
                log.info("Configuration loaded from %s", self.config_path)
                self._notify_handlers(ConfigEvent.LOADED, {"config": self.config})
        except Exception as e:
            self._mark_error_on_load(e)
            raise

    def _mark_error_on_load(self, e: Exception):
        self.health.file_exists = self.config_path.exists()
        self.health.file_readable = os.access(self.config_path, os.R_OK) if self.health.file_exists else False
        self.health.syntax_valid = False  # likely parse/validate failure
        self.health.status = "error"
        self.health.last_update = datetime.now()

        change = ConfigChange(
            timestamp=datetime.now(),
            event=ConfigEvent.ERROR,
            version=self.current_version,
            error=e,
        )
        self._record_change(change)
        log.error("Failed to load configuration: %s", e, exc_info=e)
        self._notify_handlers(ConfigEvent.ERROR, {"error": e})

    def _record_change(self, change: ConfigChange):
        """Record a configuration change in the change log."""
        self.change_log.append(change)
        
        # Trim change log if it exceeds max size
        if len(self.change_log) > self.max_change_log_size:
            self.change_log = self.change_log[-self.max_change_log_size:]

    # ---- Public API ----
    def get_config(self) -> CryptoAIBotConfig:
        with self._update_lock:
            if self.config is None:
                raise RuntimeError("Configuration not loaded")
            return self.config

    def reload_config(self) -> bool:
        """Reload configuration from file (manual or via hot-reload)."""
        try:
            with self._update_lock:
                # Avoid reloads if bytes unchanged
                if self.config_path.exists():
                    new_hash = self._file_sha256(self.config_path)
                    if new_hash and self.last_file_hash and new_hash == self.last_file_hash:
                        return True  # no-op

                old_config = self.config
                new_config, validation_report = load_and_validate_config(str(self.config_path))

                # Warn but proceed if degraded
                if not validation_report.get("deployment_ready", False):
                    log.warning("New configuration has validation issues (proceeding).")

                # Save old to history (deep copy)
                if old_config is not None:
                    self._save_to_history(old_config)

                self.config = new_config
                self.current_version = self._increment_version()

                # Apply runtime overrides on top
                self._apply_runtime_overrides_locked()  # assumes lock held

                # Update health
                self.health.status = "healthy" if validation_report.get("deployment_ready", False) else "degraded"
                self.health.last_update = datetime.now()
                self.health.version = self.current_version
                self.health.validation_errors = validation_report.get("strategy_issues", [])
                self.health.warnings = validation_report.get("performance_issues", [])
                self.health.file_exists = self.config_path.exists()
                self.health.file_readable = os.access(self.config_path, os.R_OK) if self.health.file_exists else False
                self.health.syntax_valid = True

                if self.config_path.exists():
                    self.last_file_mtime = self.config_path.stat().st_mtime
                    self.last_file_hash = self._file_sha256(self.config_path)

                # Changes diff
                changes = self._detect_changes(old_config, new_config) if old_config is not None else {}

                change = ConfigChange(
                    timestamp=datetime.now(),
                    event=ConfigEvent.UPDATED,
                    version=self.current_version,
                    changes=changes,
                    rollback_available=len(self.config_history) > 0,
                )
                self._record_change(change)

                log.info("Configuration reloaded (version %s)", self.current_version)
                self._notify_handlers(ConfigEvent.UPDATED, {"config": self.config, "changes": changes})
                return True

        except Exception as e:
            self.health.status = "error"
            change = ConfigChange(
                timestamp=datetime.now(),
                event=ConfigEvent.ERROR,
                version=self.current_version,
                error=e,
            )
            self._record_change(change)
            log.error("Failed to reload configuration: %s", e, exc_info=e)
            self._notify_handlers(ConfigEvent.ERROR, {"error": e})
            return False

    def rollback_config(self, steps: int = 1) -> bool:
        """Rollback to a previous configuration snapshot."""
        try:
            with self._update_lock:
                if steps < 1 or len(self.config_history) < steps:
                    raise ValueError(f"Not enough history for {steps} step rollback")

                target_config = self.config_history[-steps]
                # Trim snapshots we just rolled back over
                self.config_history = self.config_history[:-steps]

                self.config = deepcopy(target_config)
                self.current_version = self._increment_version()

                change = ConfigChange(
                    timestamp=datetime.now(),
                    event=ConfigEvent.ROLLBACK,
                    version=self.current_version,
                    changes={"rollback_steps": steps},
                )
                self._record_change(change)

                log.warning("Rolled back %d step(s) to version %s", steps, self.current_version)
                self._notify_handlers(ConfigEvent.ROLLBACK, {"config": self.config, "steps": steps})
                return True

        except Exception as e:
            log.error("Failed to rollback configuration: %s", e, exc_info=e)
            return False

    # ---- Runtime overrides ----
    def set_runtime_override(self, path: str, value: Any):
        """Set a runtime override (dot-path, supports list indices: a.b[0].c)."""
        with self._update_lock:
            self.runtime_overrides[path] = value
            self._apply_runtime_overrides_locked()
            log.info("Runtime override set: %s = %r", path, value)

    def remove_runtime_override(self, path: str):
        with self._update_lock:
            if path in self.runtime_overrides:
                del self.runtime_overrides[path]
                self._apply_runtime_overrides_locked()
                log.info("Runtime override removed: %s", path)

    def clear_runtime_overrides(self):
        with self._update_lock:
            self.runtime_overrides.clear()
            # Reload to reset derived state, then re-apply (none)
            self.reload_config()
            log.info("All runtime overrides cleared")

    def _apply_runtime_overrides_locked(self):
        """Apply runtime overrides to current config (lock must be held)."""
        if not self.runtime_overrides or self.config is None:
            return

        cfg_dict = self._to_dict(self.config)

        for path, value in self.runtime_overrides.items():
            self._set_nested_value(cfg_dict, path, value)

        try:
            # Reconstruct strongly typed config
            self.config = CryptoAIBotConfig(**cfg_dict)
        except Exception as e:
            log.error("Failed to apply runtime overrides: %s", e, exc_info=e)

    # --- path utils / coercion ---
    @staticmethod
    def _parse_path(path: str):
        """Parse 'a.b[0].c' with support for escaped dots: 'a.b\\.withdot'."""
        tokens: List[Union[str, int]] = []
        buf = ""
        i = 0
        while i < len(path):
            c = path[i]
            if c == "\\" and i + 1 < len(path):
                buf += path[i + 1]; i += 2; continue
            if c == ".":
                if buf:
                    tokens.append(buf); buf = ""
                i += 1; continue
            if c == "[":
                if buf:
                    tokens.append(buf); buf = ""
                j = path.find("]", i)
                if j == -1:
                    raise ValueError(f"Unclosed index in path: {path}")
                idx = int(path[i + 1 : j])
                tokens.append(idx)
                i = j + 1; continue
            buf += c; i += 1
        if buf:
            tokens.append(buf)
        return tokens

    @staticmethod
    def _coerce_value(current_value: Any, new_value: Any):
        """Coerce strings to the type of current_value when possible."""
        if isinstance(new_value, str) and current_value is not None:
            t = type(current_value)
            try:
                if t is bool:
                    return new_value.strip().lower() in {"1", "true", "yes", "on"}
                if t in (int, float):
                    return t(new_value)
                if t in (list, dict):
                    return json.loads(new_value)
            except Exception:
                pass
        return new_value

    def _set_nested_value(self, data: Dict[str, Any], path: str, value: Any):
        """Set data at dot/list path, creating intermediate containers as needed."""
        toks = self._parse_path(path)
        if not toks:
            raise ValueError("Empty path")
        cur: Any = data
        for i, key in enumerate(toks[:-1]):
            nxt = toks[i + 1]
            if isinstance(key, int):
                # Ensure list
                if not isinstance(cur, list):
                    raise TypeError(f"Index {key} used on non-list at {toks[:i]}")
                while len(cur) <= key:
                    cur.append({} if isinstance(nxt, (str,)) else [])
                cur = cur[key]
            else:
                # Ensure dict entry exists
                if not isinstance(cur, dict):
                    raise TypeError(f"Key '{key}' used on non-dict at {toks[:i]}")
                if key not in cur or not isinstance(cur[key], (dict, list)):
                    cur[key] = [] if isinstance(nxt, int) else {}
                cur = cur[key]
        last = toks[-1]
        if isinstance(last, int):
            if not isinstance(cur, list):
                raise TypeError(f"Index {last} used on non-list at {toks[:-1]}")
            while len(cur) <= last:
                cur.append(None)
            cur[last] = value
        else:
            if not isinstance(cur, dict):
                raise TypeError(f"Key '{last}' used on non-dict at {toks[:-1]}")
            old = cur.get(last)
            cur[last] = self._coerce_value(old, value)

    # ---- Hot reload ----
    def enable_hot_reload(self, check_interval: float = 2.0):
        """Watch the config file and auto-reload on changes (watchdog if present)."""
        if self.hot_reload_enabled:
            return

        # Try watchdog first
        try:
            from watchdog.observers import Observer  # type: ignore
            from watchdog.events import FileSystemEventHandler  # type: ignore

            class _Handler(FileSystemEventHandler):
                def __init__(self, mgr: "ConfigManager"):
                    self.mgr = mgr

                def on_modified(self, event):
                    if Path(event.src_path) == self.mgr.config_path:
                        log.info("Config modified (watchdog); reloading...")
                        # slight delay to allow atomic write finish
                        time.sleep(0.2)
                        self.mgr.reload_config()

            observer = Observer()
            handler = _Handler(self)
            observer.schedule(handler, str(self.config_path.parent), recursive=False)
            observer.start()
            self._observer = observer
            self.hot_reload_enabled = True
            log.info("Hot reload enabled (watchdog)")
            return
        except Exception:
            # Fall back to polling loop
            pass

        self.hot_reload_enabled = True
        self._watcher_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="config-watcher")
        self.file_watcher_task = self._watcher_executor.submit(self._file_watcher_loop, check_interval)
        log.info("Hot reload enabled (polling every %ss)", check_interval)

    def disable_hot_reload(self):
        """Stop hot reloading and shutdown watcher cleanly."""
        # watchdog
        try:
            if self._observer is not None:
                self._observer.stop()
                self._observer.join(timeout=3)
                self._observer = None
        except Exception:
            pass

        # polling
        self.hot_reload_enabled = False
        if self.file_watcher_task:
            try:
                self.file_watcher_task.result(timeout=5)
            except Exception:
                pass
            self.file_watcher_task = None
        if self._watcher_executor:
            self._watcher_executor.shutdown(wait=True, cancel_futures=False)
            self._watcher_executor = None
        log.info("Hot reload disabled")

    def _file_watcher_loop(self, check_interval: float):
        """File watcher loop for hot reload (runs in dedicated thread)."""
        while self.hot_reload_enabled:
            try:
                if not self.config_path.exists():
                    self.health.file_exists = False
                    time.sleep(check_interval)
                    continue

                self.health.file_exists = True
                self.health.file_readable = os.access(self.config_path, os.R_OK)

                current_mtime = self.config_path.stat().st_mtime
                if (self.last_file_mtime is None) or (current_mtime > self.last_file_mtime):
                    # Debounce + content-hash guard
                    time.sleep(0.3)
                    new_hash = self._file_sha256(self.config_path)
                    if self.last_file_hash is None or new_hash != self.last_file_hash:
                        log.info("Configuration file changed, reloading (polling)...")
                        if self.reload_config():
                            self.last_file_mtime = current_mtime

                time.sleep(check_interval)

            except Exception as e:
                log.error("File watcher error: %s", e, exc_info=e)
                time.sleep(max(check_interval * 2.0, 1.0))  # backoff on error

    # ---- Events ----
    def register_event_handler(self, event: ConfigEvent, handler: Callable):
        self.event_handlers[event].append(handler)
        log.debug("Registered handler for %s", event.value)

    def unregister_event_handler(self, event: ConfigEvent, handler: Callable):
        if handler in self.event_handlers[event]:
            self.event_handlers[event].remove(handler)

    def _notify_handlers(self, event: ConfigEvent, data: Dict[str, Any]):
        for handler in list(self.event_handlers[event]):
            try:
                handler(event, data)
            except Exception as e:
                log.error("Event handler error: %s", e, exc_info=e)

    # ---- Versioning & diffs ----
    def _save_to_history(self, config: CryptoAIBotConfig):
        self.config_history.append(deepcopy(config))
        if len(self.config_history) > self.max_history_size:
            self.config_history.pop(0)

    def _increment_version(self) -> str:
        parts = self.current_version.split(".")
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)

    def _detect_changes(
        self, old_config: Optional[CryptoAIBotConfig], new_config: CryptoAIBotConfig
    ) -> Dict[str, Any]:
        changes: Dict[str, Any] = {}
        old_dict = self._to_dict(old_config) if old_config is not None else {}
        new_dict = self._to_dict(new_config)

        def compare_nested(old: Any, new: Any, path: str = ""):
            if isinstance(new, dict) and isinstance(old, dict):
                # additions & modifications
                for k, v in new.items():
                    p = f"{path}.{k}" if path else k
                    if k not in old:
                        changes[p] = {"type": "added", "new": v}
                    else:
                        if isinstance(v, dict) and isinstance(old[k], dict):
                            compare_nested(old[k], v, p)
                        else:
                            if old[k] != v:
                                changes[p] = {"type": "modified", "old": old[k], "new": v}
                # removals
                for k in old.keys():
                    if k not in new:
                        p = f"{path}.{k}" if path else k
                        changes[p] = {"type": "removed", "old": old[k]}
            else:
                if old != new:
                    changes[path or "<root>"] = {"type": "modified", "old": old, "new": new}

        compare_nested(old_dict, new_dict)
        return changes

    # ---- Health & insights ----
    def get_health_status(self) -> ConfigHealth:
        return self.health

    def get_change_log(self, limit: Optional[int] = None) -> List[ConfigChange]:
        return self.change_log[-limit:] if limit else list(self.change_log)

    def get_version_info(self) -> Dict[str, Any]:
        return {
            "current_version": self.current_version,
            "history_size": len(self.config_history),
            "can_rollback": len(self.config_history) > 0,
            "hot_reload_enabled": self.hot_reload_enabled,
            "runtime_overrides": len(self.runtime_overrides),
            "last_update": self.health.last_update.isoformat(),
        }

    def export_config(self, format: str = "yaml") -> str:
        if not self.config:
            raise RuntimeError("No configuration loaded")
        cfg = self._to_dict(self.config)
        fmt = format.lower()
        if fmt == "json":
            return json.dumps(cfg, indent=2)
        if fmt == "yaml":
            return yaml.safe_dump(cfg, sort_keys=False)
        raise ValueError(f"Unsupported format: {format}")

    def validate_current_config(self) -> Dict[str, Any]:
        """Run validations using your project's ConfigValidator."""
        if not self.config:
            return {"valid": False, "error": "No configuration loaded"}
        try:
            validator = ConfigValidator()
            strat = getattr(validator, "validate_strategy_consistency", lambda c: [])(self.config)
            risk  = getattr(validator, "validate_risk_parameters",   lambda c: [])(self.config)
            perf  = getattr(validator, "validate_performance_settings", lambda c: [])(self.config)
            total = len(strat) + len(risk) + len(perf)
            return {
                "valid": True,
                "strategy_issues": strat,
                "risk_issues": risk,
                "performance_issues": perf,
                "total_issues": total,
                "deployment_ready": total == 0,
            }
        except Exception as e:
            return {"valid": False, "deployment_ready": False, "error": str(e)}

    # ---- Context & shutdown ----
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.shutdown()

    def shutdown(self):
        """Clean shutdown (stop hot reload, clear handlers)."""
        self.disable_hot_reload()
        for handlers in self.event_handlers.values():
            handlers.clear()
        log.info("Configuration manager shutdown")


# ----------------------------
# Module-level convenience API
# ----------------------------
def _get_or_create_manager(config_path: str = "config/settings.yaml") -> ConfigManager:
    return ConfigManager.get_instance(config_path)


def get_config(config_path: str = "config/settings.yaml") -> CryptoAIBotConfig:
    """Main accessor expected by TradingAgent and the rest of the system."""
    return _get_or_create_manager(config_path).get_config()


def get_config_manager(config_path: str = "config/settings.yaml") -> ConfigManager:
    return _get_or_create_manager(config_path)


def reload_config() -> bool:
    return get_config_manager().reload_config()


def enable_hot_reload(check_interval: float = 2.0):
    get_config_manager().enable_hot_reload(check_interval)


def disable_hot_reload():
    get_config_manager().disable_hot_reload()


def set_config_override(path: str, value: Any):
    get_config_manager().set_runtime_override(path, value)


def get_config_health() -> ConfigHealth:
    return get_config_manager().get_health_status()


def get_config_version() -> Dict[str, Any]:
    return get_config_manager().get_version_info()


# Backwards compatibility: old helper name
def reload_config_legacy(config_path: str = "config/settings.yaml") -> CryptoAIBotConfig:
    mgr = get_config_manager(config_path)
    mgr.reload_config()
    return mgr.get_config()


def validate_deployment_enhanced(config_path: str = "config/settings.yaml") -> Dict[str, Any]:
    """
    Enhanced deployment validation with manager health context.
    """
    try:
        mgr = get_config_manager(config_path)
        report = mgr.validate_current_config()
        health = mgr.get_health_status()
        report["config_health"] = {
            "status": health.status,
            "file_exists": health.file_exists,
            "file_readable": health.file_readable,
            "syntax_valid": health.syntax_valid,
        }
        report.setdefault("deployment_ready", report.get("valid", False) and report.get("total_issues", 1) == 0)
        return report
    except Exception as e:
        return {
            "valid": False,
            "deployment_ready": False,
            "error": str(e),
            "config_health": {"status": "error"},
        }


__all__ = [
    # Expected by TradingAgent
    "get_config",
    # Enhanced management
    "get_config_manager",
    "ConfigManager",
    "ConfigHealth",
    "ConfigChange",
    "ConfigEvent",
    # Ops helpers
    "reload_config",
    "enable_hot_reload",
    "disable_hot_reload",
    "set_config_override",
    "get_config_health",
    "get_config_version",
    # Validation
    "validate_deployment_enhanced",
    # Back-compat
    "reload_config_legacy",
]
