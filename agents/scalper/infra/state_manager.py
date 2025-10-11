# agents/scalper/infra/state_manager.py
"""
Production-grade state management for trading agents.
Provides persistent state storage, versioning, and recovery capabilities.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import pickle
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import redis.asyncio as redis  # redis-py asyncio API

from utils.logger import get_logger


class StateFormat(str, Enum):
    """State serialization formats."""

    JSON = "json"
    PICKLE = "pickle"
    COMPRESSED = "compressed"  # gzip-compressed JSON bytes


class StateOperation(str, Enum):
    """State operation types."""

    SAVE = "save"
    LOAD = "load"
    DELETE = "delete"
    SNAPSHOT = "snapshot"
    RESTORE = "restore"


@dataclass
class StateSnapshot:
    """Represents a state snapshot."""

    version: str
    timestamp: float
    checksum: str
    data_size: int
    format: StateFormat
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StateMetrics:
    """State management performance metrics."""

    saves_completed: int = 0
    loads_completed: int = 0
    save_errors: int = 0
    load_errors: int = 0
    avg_save_time_ms: float = 0.0
    avg_load_time_ms: float = 0.0
    total_data_saved_mb: float = 0.0
    total_data_loaded_mb: float = 0.0
    last_save_time: Optional[float] = None
    last_load_time: Optional[float] = None


class StateManager:
    """
    Production-grade state manager for trading agents.

    Features:
    - Redis-backed persistence with fallback to local files
    - Automatic versioning and checksums
    - Compression for large state objects
    - Snapshot management with configurable retention
    - Recovery mechanisms for corrupted state
    - Performance monitoring and metrics
    """

    def __init__(
        self,
        agent_id: str,
        redis_client: Optional[redis.Redis] = None,
        local_backup_path: Optional[str] = None,
        max_snapshots: int = 10,
        compression_threshold_kb: int = 100,
        checksum_validation: bool = True,
    ):
        self.agent_id = agent_id
        self.redis_client = redis_client
        self.local_backup_path = Path(local_backup_path or f"data/state/{agent_id}")
        self.max_snapshots = max_snapshots
        self.compression_threshold_kb = compression_threshold_kb
        self.checksum_validation = checksum_validation

        # State management
        self.current_version = "1.0.0"
        self.snapshots: List[StateSnapshot] = []
        self.current_state: Optional[Dict[str, Any]] = None
        self.state_lock = asyncio.Lock()

        # Performance tracking
        self.metrics = StateMetrics()

        # Redis keys
        self.redis_key_prefix = f"agent:{agent_id}:state"
        self.redis_snapshot_prefix = f"agent:{agent_id}:snapshots"
        self.redis_metadata_key = f"{self.redis_key_prefix}:metadata"

        # Logging
        self.logger = get_logger(f"state_manager.{agent_id}")

        # Ensure local backup directory exists
        self.local_backup_path.mkdir(parents=True, exist_ok=True)

    # ---------- Public API ----------

    async def initialize(self) -> bool:
        """Initialize state manager, check Redis, load snapshot index & current state."""
        try:
            self.logger.info(f"[{self.agent_id}] Initializing state manager")

            # Verify Redis connection if provided
            if self.redis_client:
                try:
                    await self.redis_client.ping()
                    self.logger.info("Redis connection verified")
                except Exception as e:
                    self.logger.warning(
                        f"Redis connection failed; continuing with local persistence only: {e}"
                    )
                    self.redis_client = None

            # Load available snapshots (local index)
            await self._load_snapshot_index()

            # Attempt to load current state
            current = await self.load_state()
            if current:
                self.current_state = current
                self.logger.info(f"Loaded existing state (version: {self.current_version})")
            else:
                self.logger.info("No existing state found; starting fresh")

            return True
        except Exception as e:
            self.logger.error(f"Failed to initialize state manager: {e}")
            return False

    async def save_state(
        self,
        state_data: Dict[str, Any],
        create_snapshot: bool = False,
        format: StateFormat = StateFormat.JSON,
    ) -> bool:
        """
        Save agent state with optional snapshot creation.
        Automatically upgrades to COMPRESSED if JSON payload exceeds threshold.
        """
        start = time.perf_counter()

        async with self.state_lock:
            try:
                # Serialize (auto-compress if large)
                serialized_data, used_format = await self._serialize_with_policy(
                    state_data, format
                )

                checksum = (
                    self._calculate_checksum(serialized_data)
                    if self.checksum_validation
                    else None
                )

                # Try Redis
                redis_ok = False
                if self.redis_client:
                    redis_ok = await self._save_to_redis(serialized_data, checksum, used_format)

                # Always save local
                local_ok = await self._save_to_local(serialized_data, checksum, used_format)

                # Update current state cache
                self.current_state = state_data.copy()

                # Optional snapshot
                if create_snapshot:
                    await self._create_snapshot(serialized_data, used_format, checksum)

                # Metrics
                elapsed_ms = (time.perf_counter() - start) * 1000
                self._update_save_metrics(len(serialized_data), elapsed_ms)

                success = redis_ok or local_ok
                if success:
                    self.logger.debug(
                        f"State saved (format={used_format.value}, size={len(serialized_data)} bytes)"
                    )
                else:
                    self.logger.error("Failed to save state to both Redis and local backup")
                return success

            except Exception as e:
                self.metrics.save_errors += 1
                self.logger.error(f"Error saving state: {e}")
                return False

    async def load_state(self, version: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Load agent state (current or specific snapshot version)."""
        start = time.perf_counter()

        async with self.state_lock:
            try:
                # Prefer Redis
                data = None
                if self.redis_client:
                    data = await self._load_from_redis(version)

                # Local fallback
                if data is None:
                    data = await self._load_from_local(version)

                if data is None:
                    self.logger.debug("No state data available to load")
                    return None

                elapsed_ms = (time.perf_counter() - start) * 1000
                # We don't know the exact bytes post-deserialization; approximate with json length
                try:
                    size_hint = len(json.dumps(data))
                except Exception:
                    size_hint = len(str(data))
                self._update_load_metrics(size_hint, elapsed_ms)

                self.logger.debug("State loaded successfully")
                return data
            except Exception as e:
                self.metrics.load_errors += 1
                self.logger.error(f"Error loading state: {e}")
                return None

    async def delete_state(self, version: Optional[str] = None) -> bool:
        """Delete current state or a specific snapshot."""
        async with self.state_lock:
            try:
                redis_success = True
                local_success = True

                # Redis
                if self.redis_client:
                    try:
                        if version:
                            await self.redis_client.delete(
                                f"{self.redis_snapshot_prefix}:{version}",
                                f"{self.redis_snapshot_prefix}:{version}:metadata",
                            )
                        else:
                            await self.redis_client.delete(
                                self.redis_key_prefix, self.redis_metadata_key
                            )
                    except Exception as e:
                        self.logger.warning(f"Failed to delete from Redis: {e}")
                        redis_success = False

                # Local files
                try:
                    if version:
                        df = self._snapshot_data_file(version)
                        mf = self._snapshot_meta_file(version)
                        if df.exists():
                            df.unlink()
                        if mf.exists():
                            mf.unlink()
                        # Remove from in-memory index if present
                        self.snapshots = [s for s in self.snapshots if s.version != version]
                    else:
                        df = self._current_data_file()
                        mf = self._current_meta_file()
                        if df.exists():
                            df.unlink()
                        if mf.exists():
                            mf.unlink()
                        self.current_state = None
                except Exception as e:
                    self.logger.warning(f"Failed to delete local state: {e}")
                    local_success = False

                success = redis_success or local_success
                self.logger.info(f"State deletion {'successful' if success else 'failed'}")
                return success
            except Exception as e:
                self.logger.error(f"Error deleting state: {e}")
                return False

    async def create_checkpoint(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Create a named checkpoint from the current state."""
        if self.current_state is None:
            self.logger.warning("No current state to checkpoint")
            return False

        try:
            # Freeze current as JSON (deterministic)
            serialized = await self._serialize_data(self.current_state, StateFormat.JSON)
            checksum = self._calculate_checksum(serialized) if self.checksum_validation else ""
            version = f"checkpoint_{name}_{int(time.time())}"

            snapshot = StateSnapshot(
                version=version,
                timestamp=time.time(),
                checksum=checksum,
                data_size=len(serialized),
                format=StateFormat.JSON,
                metadata=metadata or {},
            )

            ok = await self._save_snapshot(snapshot, serialized)
            if ok:
                self.logger.info(f"Checkpoint '{name}' created")
            else:
                self.logger.error(f"Failed to create checkpoint '{name}'")
            return ok
        except Exception as e:
            self.logger.error(f"Error creating checkpoint: {e}")
            return False

    async def restore_checkpoint(self, name: str) -> bool:
        """Restore state from a named checkpoint."""
        try:
            target = next(
                (s for s in self.snapshots if s.version.startswith(f"checkpoint_{name}_")), None
            )
            if target is None:
                self.logger.error(f"Checkpoint '{name}' not found")
                return False

            data = await self.load_state(target.version)
            if data is None:
                self.logger.error(f"Failed to load checkpoint data for '{name}'")
                return False

            ok = await self.save_state(data)
            if ok:
                self.logger.info(f"Checkpoint '{name}' restored")
            else:
                self.logger.error(f"Failed to restore checkpoint '{name}'")
            return ok
        except Exception as e:
            self.logger.error(f"Error restoring checkpoint: {e}")
            return False

    async def get_snapshots(self) -> List[StateSnapshot]:
        """Return a copy of the snapshot list."""
        return list(self.snapshots)

    async def get_state_info(self) -> Dict[str, Any]:
        """Get comprehensive state information for diagnostics."""
        return {
            "agent_id": self.agent_id,
            "current_version": self.current_version,
            "has_current_state": self.current_state is not None,
            "current_state_size": len(json.dumps(self.current_state)) if self.current_state else 0,
            "snapshots_count": len(self.snapshots),
            "redis_available": self.redis_client is not None,
            "local_backup_path": str(self.local_backup_path),
            "metrics": asdict(self.metrics),
            "snapshots": [asdict(s) for s in self.snapshots[-5:]],
        }

    async def cleanup_old_snapshots(self) -> int:
        """Enforce snapshot retention; delete oldest beyond `max_snapshots`."""
        if len(self.snapshots) <= self.max_snapshots:
            return 0

        # Oldest first
        to_delete = sorted(self.snapshots, key=lambda s: s.timestamp)[: -self.max_snapshots]
        deleted = 0

        for s in to_delete:
            try:
                # Redis
                if self.redis_client:
                    await self.redis_client.delete(
                        f"{self.redis_snapshot_prefix}:{s.version}",
                        f"{self.redis_snapshot_prefix}:{s.version}:metadata",
                    )
                # Local
                df = self._snapshot_data_file(s.version)
                mf = self._snapshot_meta_file(s.version)
                if df.exists():
                    df.unlink()
                if mf.exists():
                    mf.unlink()

                self.snapshots.remove(s)
                deleted += 1
            except Exception as e:
                self.logger.warning(f"Failed to delete snapshot {s.version}: {e}")

        if deleted:
            self.logger.info(f"Cleaned up {deleted} old snapshots")
        return deleted

    async def close(self):
        """Close state manager; persist current state & close Redis."""
        try:
            if self.current_state:
                await self.save_state(self.current_state)

            if self.redis_client:
                # redis.asyncio.Redis.close is synchronous; ensure connections are closed
                try:
                    self.redis_client.close()  # type: ignore[attr-defined]
                except Exception:
                    pass
                try:
                    await self.redis_client.connection_pool.disconnect(inuse_connections=True)  # type: ignore
                except Exception:
                    pass

            self.logger.info("State manager closed")
        except Exception as e:
            self.logger.error(f"Error closing state manager: {e}")

    # ---------- Internal helpers ----------

    async def _serialize_with_policy(
        self, data: Any, requested_format: StateFormat
    ) -> tuple[bytes, StateFormat]:
        """
        Serialize and auto-upgrade to COMPRESSED if JSON payload exceeds threshold.
        """
        if requested_format == StateFormat.JSON:
            raw = await self._serialize_data(data, StateFormat.JSON)
            if len(raw) > self.compression_threshold_kb * 1024:
                # Compress large payloads
                import gzip

                compressed = gzip.compress(raw)
                return compressed, StateFormat.COMPRESSED
            return raw, StateFormat.JSON
        else:
            raw = await self._serialize_data(data, requested_format)
            return raw, requested_format

    async def _serialize_data(self, data: Any, format: StateFormat) -> bytes:
        """Serialize data to bytes."""
        if format == StateFormat.JSON:
            return json.dumps(data, default=str, separators=(",", ":")).encode("utf-8")
        if format == StateFormat.PICKLE:
            return pickle.dumps(data, protocol=pickle.HIGHEST_PROTOCOL)
        if format == StateFormat.COMPRESSED:
            import gzip

            raw = json.dumps(data, default=str, separators=(",", ":")).encode("utf-8")
            return gzip.compress(raw)
        raise ValueError(f"Unsupported format: {format}")

    async def _deserialize_data(self, data: bytes, format: StateFormat) -> Any:
        """Deserialize bytes to Python object."""
        if format == StateFormat.JSON:
            return json.loads(data.decode("utf-8"))
        if format == StateFormat.PICKLE:
            return pickle.loads(data)
        if format == StateFormat.COMPRESSED:
            import gzip

            raw = gzip.decompress(data)
            return json.loads(raw.decode("utf-8"))
        raise ValueError(f"Unsupported format: {format}")

    def _calculate_checksum(self, data: bytes) -> str:
        """MD5 checksum (fast, adequate for corruption detection)."""
        return hashlib.md5(data).hexdigest()

    def _validate_checksum(self, data: bytes, expected_checksum: str) -> bool:
        if not self.checksum_validation:
            return True
        return self._calculate_checksum(data) == expected_checksum

    # ----- Redis path -----

    async def _save_to_redis(self, data: bytes, checksum: Optional[str], fmt: StateFormat) -> bool:
        """Save current state to Redis."""
        try:
            meta = {
                "version": self.current_version,
                "timestamp": time.time(),
                "format": fmt.value,
                "size": len(data),
            }
            if checksum:
                meta["checksum"] = checksum

            async with self.redis_client.pipeline(transaction=False) as pipe:  # type: ignore
                pipe.set(self.redis_key_prefix, data)
                pipe.set(self.redis_metadata_key, json.dumps(meta))
                await pipe.execute()

            return True
        except Exception as e:
            self.logger.warning(f"Failed to save to Redis: {e}")
            return False

    async def _load_from_redis(self, version: Optional[str]) -> Optional[Dict[str, Any]]:
        """Load state (current or snapshot) from Redis."""
        try:
            if version:
                key = f"{self.redis_snapshot_prefix}:{version}"
                meta_key = f"{key}:metadata"
            else:
                key = self.redis_key_prefix
                meta_key = self.redis_metadata_key

            data, meta_raw = await asyncio.gather(
                self.redis_client.get(key), self.redis_client.get(meta_key)
            )

            if data is None:
                return None

            metadata: Dict[str, Any] = {}
            if meta_raw is not None:
                if isinstance(meta_raw, bytes):
                    meta_raw = meta_raw.decode("utf-8")
                try:
                    metadata = json.loads(meta_raw)
                except Exception:
                    metadata = {}

            fmt = StateFormat(metadata.get("format", StateFormat.JSON.value))

            if self.checksum_validation and "checksum" in metadata:
                if not self._validate_checksum(data, metadata["checksum"]):
                    self.logger.error("Redis data checksum validation failed")
                    return None

            return await self._deserialize_data(data, fmt)
        except Exception as e:
            self.logger.warning(f"Failed to load from Redis: {e}")
            return None

    # ----- Local path -----

    def _current_data_file(self) -> Path:
        return self.local_backup_path / "current_state.data"

    def _current_meta_file(self) -> Path:
        return self.local_backup_path / "current_state.metadata"

    def _snapshot_data_file(self, version: str) -> Path:
        return self.local_backup_path / f"snapshot_{version}.data"

    def _snapshot_meta_file(self, version: str) -> Path:
        return self.local_backup_path / f"snapshot_{version}.metadata"

    async def _save_to_local(self, data: bytes, checksum: Optional[str], fmt: StateFormat) -> bool:
        """Save current state to local files."""
        try:
            df = self._current_data_file()
            mf = self._current_meta_file()

            df.write_bytes(data)

            meta = {
                "version": self.current_version,
                "timestamp": time.time(),
                "format": fmt.value,
                "size": len(data),
            }
            if checksum:
                meta["checksum"] = checksum
            mf.write_text(json.dumps(meta, indent=2))

            return True
        except Exception as e:
            self.logger.warning(f"Failed to save to local backup: {e}")
            return False

    async def _load_from_local(self, version: Optional[str]) -> Optional[Dict[str, Any]]:
        """Load current/snapshot state from local files."""
        try:
            if version:
                df = self._snapshot_data_file(version)
                mf = self._snapshot_meta_file(version)
            else:
                df = self._current_data_file()
                mf = self._current_meta_file()

            if not df.exists():
                return None

            data = df.read_bytes()
            metadata: Dict[str, Any] = {}
            if mf.exists():
                try:
                    metadata = json.loads(mf.read_text())
                except Exception:
                    metadata = {}

            if self.checksum_validation and metadata.get("checksum"):
                if not self._validate_checksum(data, metadata["checksum"]):
                    self.logger.error("Local backup checksum validation failed")
                    return None

            fmt = StateFormat(metadata.get("format", StateFormat.JSON.value))
            return await self._deserialize_data(data, fmt)
        except Exception as e:
            self.logger.warning(f"Failed to load from local backup: {e}")
            return None

    # ----- Snapshots -----

    async def _create_snapshot(self, data: bytes, fmt: StateFormat, checksum: Optional[str]):
        """Create and persist a new versioned snapshot from raw bytes."""
        try:
            snapshot = StateSnapshot(
                version=self._increment_version(),
                timestamp=time.time(),
                checksum=checksum or "",
                data_size=len(data),
                format=fmt,
            )
            await self._save_snapshot(snapshot, data)
        except Exception as e:
            self.logger.error(f"Failed to create snapshot: {e}")

    async def _save_snapshot(self, snapshot: StateSnapshot, data: bytes) -> bool:
        """Persist snapshot to Redis (if available) and local storage."""
        try:
            # Redis
            if self.redis_client:
                async with self.redis_client.pipeline(transaction=False) as pipe:  # type: ignore
                    pipe.set(f"{self.redis_snapshot_prefix}:{snapshot.version}", data)
                    pipe.set(
                        f"{self.redis_snapshot_prefix}:{snapshot.version}:metadata",
                        json.dumps(asdict(snapshot)),
                    )
                    await pipe.execute()

            # Local
            self._snapshot_data_file(snapshot.version).write_bytes(data)
            self._snapshot_meta_file(snapshot.version).write_text(
                json.dumps(asdict(snapshot), indent=2)
            )

            self.snapshots.append(snapshot)
            await self.cleanup_old_snapshots()
            return True
        except Exception as e:
            self.logger.error(f"Failed to save snapshot: {e}")
            return False

    async def _load_snapshot_index(self):
        """Load snapshot metadata from local directory to build in-memory index."""
        try:
            metas = list(self.local_backup_path.glob("snapshot_*.metadata"))
            for mf in metas:
                try:
                    meta = json.loads(mf.read_text())
                    snap = StateSnapshot(
                        version=meta["version"],
                        timestamp=meta["timestamp"],
                        checksum=meta.get("checksum", ""),
                        data_size=meta.get("data_size", 0),
                        format=StateFormat(meta.get("format", StateFormat.JSON.value)),
                        metadata=meta.get("metadata", {}),
                    )
                    self.snapshots.append(snap)
                except Exception as e:
                    self.logger.warning(f"Invalid snapshot metadata in {mf}: {e}")

            # sort by timestamp ascending
            self.snapshots.sort(key=lambda s: s.timestamp)
            self.logger.debug(f"Loaded {len(self.snapshots)} snapshot descriptors")
        except Exception as e:
            self.logger.warning(f"Failed to load snapshot index: {e}")

    def _increment_version(self) -> str:
        """Increment semantic-like patch version: x.y.Z."""
        parts = self.current_version.split(".")
        try:
            parts[-1] = str(int(parts[-1]) + 1)
        except Exception:
            parts[-1] = "1"
        self.current_version = ".".join(parts)
        return self.current_version

    # ----- Metrics -----

    def _update_save_metrics(self, data_size: int, time_ms: float):
        self.metrics.saves_completed += 1
        self.metrics.total_data_saved_mb += data_size / (1024 * 1024)
        self.metrics.last_save_time = time.time()
        if self.metrics.saves_completed == 1:
            self.metrics.avg_save_time_ms = time_ms
        else:
            n = self.metrics.saves_completed
            self.metrics.avg_save_time_ms = (self.metrics.avg_save_time_ms * (n - 1) + time_ms) / n

    def _update_load_metrics(self, data_size: int, time_ms: float):
        self.metrics.loads_completed += 1
        self.metrics.total_data_loaded_mb += data_size / (1024 * 1024)
        self.metrics.last_load_time = time.time()
        if self.metrics.loads_completed == 1:
            self.metrics.avg_load_time_ms = time_ms
        else:
            n = self.metrics.loads_completed
            self.metrics.avg_load_time_ms = (self.metrics.avg_load_time_ms * (n - 1) + time_ms) / n


# Convenience factory
async def create_state_manager(
    agent_id: str,
    redis_client: Optional[redis.Redis] = None,
    **kwargs,
) -> StateManager:
    mgr = StateManager(agent_id, redis_client, **kwargs)
    await mgr.initialize()
    return mgr


__all__ = [
    "StateManager",
    "StateSnapshot",
    "StateMetrics",
    "StateFormat",
    "StateOperation",
    "create_state_manager",
]
