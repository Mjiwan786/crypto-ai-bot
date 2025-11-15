"""
Production-Ready Kraken WebSocket Client
Redis Cloud Optimized with all syntax errors fixed
Designed for deployment with crypto-ai-bot architecture
"""

import asyncio
import json
import logging
import time
import os
import random
from typing import Dict, List, Optional, Callable, Any
from enum import Enum
from collections import deque
import websockets
import redis.asyncio as redis
import orjson
from datetime import datetime
from contextlib import asynccontextmanager
from pydantic import BaseModel, field_validator, Field

# Prometheus metrics (optional) - PRD-001 Section 4.1, 4.2, 1.3 & 8.2
try:
    from prometheus_client import Counter
    KRAKEN_WS_CONNECTIONS_TOTAL = Counter(
        'kraken_ws_connections_total',
        'Total WebSocket connection state changes',
        ['state']
    )
    KRAKEN_WS_RECONNECTS_TOTAL = Counter(
        'kraken_ws_reconnects_total',
        'Total WebSocket reconnection attempts'
    )
    KRAKEN_WS_MESSAGE_GAPS_TOTAL = Counter(
        'kraken_ws_message_gaps_total',
        'Total message sequence gaps detected',
        ['channel']
    )
    KRAKEN_WS_STALE_MESSAGES_TOTAL = Counter(
        'kraken_ws_stale_messages_total',
        'Total stale or future-dated messages rejected',
        ['channel', 'reason']
    )
    KRAKEN_WS_DUPLICATES_REJECTED_TOTAL = Counter(
        'kraken_ws_duplicates_rejected_total',
        'Total duplicate messages rejected',
        ['channel']
    )
    KRAKEN_WS_ERRORS_TOTAL = Counter(
        'kraken_ws_errors_total',
        'Total WebSocket errors by type',
        ['error_type']
    )
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False
    KRAKEN_WS_CONNECTIONS_TOTAL = None
    KRAKEN_WS_RECONNECTS_TOTAL = None
    KRAKEN_WS_MESSAGE_GAPS_TOTAL = None
    KRAKEN_WS_STALE_MESSAGES_TOTAL = None
    KRAKEN_WS_DUPLICATES_REJECTED_TOTAL = None
    KRAKEN_WS_ERRORS_TOTAL = None

# Discord alerts (optional) - PRD-001 Section 4.2
try:
    from monitoring.discord_alerts import send_alert
    DISCORD_ALERTS_AVAILABLE = True
except ImportError:
    DISCORD_ALERTS_AVAILABLE = False
    send_alert = None


class ConnectionState(str, Enum):
    """WebSocket connection states per PRD-001 Section 4.1"""
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    RECONNECTING = "reconnecting"

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

# Pydantic configuration validation - Redis Cloud Optimized
class KrakenWSConfig(BaseModel):
    """Validated configuration matching YAML specs - Redis Cloud Optimized"""
    url: str = Field(default="wss://ws.kraken.com", pattern=r"^wss?://.*")
    pairs: List[str] = Field(
        default_factory=lambda: os.getenv(
            "TRADING_PAIRS", "BTC/USD,ETH/USD,SOL/USD,MATIC/USD,LINK/USD"
        ).split(",")
    )
    timeframes: List[str] = Field(
        default_factory=lambda: os.getenv("TIMEFRAMES", "15s,1m,3m,5m").split(",")
    )
    redis_url: str = Field(default_factory=lambda: os.getenv("REDIS_URL", ""))
    redis_streams: Dict[str, str] = Field(default_factory=lambda: {
        "ticker": "kraken:ticker",
        "trade": "kraken:trade",
        "spread": "kraken:spread",
        "book": "kraken:book",
        "ohlc": "kraken:ohlc",
        "scalp_signals": "kraken:scalp"
    })
    
    # UPDATED: Redis Cloud optimized connection settings (PRD-001 compliant)
    reconnect_delay: int = Field(
        default=int(os.getenv("WEBSOCKET_RECONNECT_DELAY", "1")), ge=1, le=60
    )
    max_retries: int = Field(default=int(os.getenv("WEBSOCKET_MAX_RETRIES", "10")), ge=1, le=100)
    ping_interval: int = Field(default=int(os.getenv("WEBSOCKET_PING_INTERVAL", "30")), ge=5, le=60)
    ping_timeout: int = Field(default=int(os.getenv("WEBSOCKET_PING_TIMEOUT", "60")), ge=10, le=120)
    close_timeout: int = Field(default=int(os.getenv("WEBSOCKET_CLOSE_TIMEOUT", "5")), ge=1, le=30)
    book_depth: int = Field(default=10, ge=5, le=1000)
    heartbeat_interval: int = Field(default=15, ge=10, le=300)
    
    # FIXED: Redis Cloud connection pooling optimization
    redis_pool_size: int = Field(
        default=int(os.getenv("REDIS_CONNECTION_POOL_SIZE", "10")), ge=1, le=100
    )
    redis_socket_timeout: int = Field(
        default=int(os.getenv("REDIS_SOCKET_TIMEOUT", "10")), ge=5, le=120
    )
    
    # UPDATED: Circuit breaker settings for Redis Cloud
    max_spread_bps: float = Field(
        default=float(os.getenv("SPREAD_BPS_MAX", "5.0")), ge=0.1, le=100.0
    )
    max_latency_ms: float = Field(
        default=float(os.getenv("LATENCY_MS_MAX", "100.0")), ge=10, le=5000
    )
    max_consecutive_errors: int = Field(
        default=int(os.getenv("CIRCUIT_BREAKER_REDIS_ERRORS", "3")), ge=1, le=50
    )
    circuit_breaker_cooldown: int = Field(
        default=int(os.getenv("CIRCUIT_BREAKER_COOLDOWN_SECONDS", "45")), ge=10, le=600
    )
    
    # UPDATED: Scalping settings for Redis Cloud
    scalp_enabled: bool = Field(default=os.getenv("SCALP_ENABLED", "true").lower() == "true")
    scalp_min_volume: float = Field(default=float(os.getenv("SCALP_MIN_VOLUME", "0.1")), ge=0.001)
    scalp_max_trades_per_minute: int = Field(
        default=int(os.getenv("SCALP_MAX_TRADES_PER_MINUTE", "3")), ge=1, le=60
    )
    
    # UPDATED: Performance monitoring for Redis Cloud
    enable_latency_tracking: bool = Field(
        default=os.getenv("ENABLE_LATENCY_TRACKING", "true").lower() == "true"
    )
    enable_health_monitoring: bool = Field(
        default=os.getenv("ENABLE_HEALTH_MONITORING", "true").lower() == "true"
    )
    metrics_interval: int = Field(default=int(os.getenv("METRICS_INTERVAL", "15")), ge=5, le=300)
    
    # NEW: Redis Cloud specific settings
    redis_cloud_optimized: bool = Field(
        default=os.getenv("REDIS_CLOUD_OPTIMIZED", "true").lower() == "true"
    )
    redis_batch_size: int = Field(
        default=int(os.getenv("REDIS_STREAM_BATCH_SIZE", "25")), ge=1, le=100
    )
    redis_memory_threshold_mb: int = Field(
        default=int(os.getenv("REDIS_MEMORY_THRESHOLD_MB", "100")), ge=10, le=1000
    )
    
    @field_validator("pairs")
    @classmethod
    def validate_pairs(cls, v):
        if isinstance(v, str):
            v = [p.strip() for p in v.split(",")]
        if not v:
            raise ValueError("Pairs list cannot be empty")
        
        # Validate Kraken pair format
        valid_pairs = {
            "BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XBT/USD",
            "XXBT/ZUSD", "XETH/ZUSD", "SOL/ZUSD", "ADA/ZUSD"
        }
        for pair in v:
            if pair not in valid_pairs:
                logging.warning(f"Pair {pair} not in validated list, proceed with caution")
        return v
    
    @field_validator("timeframes")
    @classmethod
    def validate_timeframes(cls, v):
        if isinstance(v, str):
            v = [tf.strip() for tf in v.split(",")]
        valid_timeframes = ["15s", "1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]
        for tf in v:
            if tf not in valid_timeframes:
                raise ValueError(f"Invalid timeframe: {tf}")
        return v
    
    @field_validator("redis_url")
    @classmethod
    def validate_redis_url(cls, v):
        if v and not (v.startswith("redis://") or v.startswith("rediss://")):
            raise ValueError("Redis URL must start with redis:// or rediss://")
        return v


class CircuitBreakerState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Circuit breaker tripped
    HALF_OPEN = "half_open" # Testing if service recovered


class CircuitBreaker:
    """Circuit breaker implementation for risk controls"""
    
    def __init__(self, name: str, failure_threshold: int = 3, timeout: int = 45):
        self.name = name
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitBreakerState.CLOSED
        self.logger = logging.getLogger(f"CircuitBreaker.{name}")
    
    async def call(self, func: Callable, *args, **kwargs):
        """Execute function through circuit breaker"""
        if self.state == CircuitBreakerState.OPEN:
            if time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitBreakerState.HALF_OPEN
                self.logger.info(f"Circuit breaker {self.name} entering HALF_OPEN state")
            else:
                raise Exception(f"Circuit breaker {self.name} is OPEN")
        
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            await self.on_success()
            return result
        except Exception:
            await self.on_failure()
            raise
    
    async def on_success(self):
        """Reset circuit breaker on success"""
        self.failure_count = 0
        if self.state == CircuitBreakerState.HALF_OPEN:
            self.state = CircuitBreakerState.CLOSED
            self.logger.info(f"Circuit breaker {self.name} reset to CLOSED")
    
    async def on_failure(self):
        """Handle failure"""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitBreakerState.OPEN
            self.logger.error(
                f"Circuit breaker {self.name} OPENED after {self.failure_count} failures"
            )


class LatencyTracker:
    """Track latency metrics for monitoring"""
    
    def __init__(self, max_samples: int = 1000):
        self.max_samples = max_samples
        self.samples = []
        self.start_times = {}
    
    def start_timing(self, operation_id: str):
        """Start timing an operation"""
        self.start_times[operation_id] = time.time()
    
    def end_timing(self, operation_id: str) -> float:
        """End timing and return latency in ms"""
        if operation_id not in self.start_times:
            return 0.0
        
        latency_ms = (time.time() - self.start_times[operation_id]) * 1000
        del self.start_times[operation_id]
        
        # Keep rolling window of samples
        self.samples.append(latency_ms)
        if len(self.samples) > self.max_samples:
            self.samples.pop(0)
        
        return latency_ms
    
    def get_stats(self) -> Dict[str, float]:
        """Get latency statistics"""
        if not self.samples:
            return {"avg": 0, "p50": 0, "p95": 0, "p99": 0, "max": 0}
        
        sorted_samples = sorted(self.samples)
        n = len(sorted_samples)
        
        return {
            "avg": sum(self.samples) / n,
            "p50": sorted_samples[int(n * 0.5)],
            "p95": sorted_samples[int(n * 0.95)],
            "p99": sorted_samples[int(n * 0.99)],
            "max": max(self.samples)
        }


class RedisConnectionManager:
    """Manage Redis connections with pooling - Redis Cloud Optimized with Fixes"""
    
    def __init__(self, config: KrakenWSConfig):
        self.config = config
        self.redis_client: Optional[redis.Redis] = None
        self.logger = logging.getLogger(__name__)
    
    @asynccontextmanager
    async def get_connection(self):
        """Get Redis connection"""
        if not self.redis_client:
            await self.initialize_pool()
        
        yield self.redis_client
    
    async def initialize_pool(self):
        """Initialize Redis connection - Redis Cloud Optimized with async fixes"""
        if not self.config.redis_url:
            self.logger.warning("No Redis URL provided, skipping Redis initialization")
            return
        
        try:
            # FIXED: Redis Cloud connection using environment variable for security
            if self.config.redis_url.startswith("rediss://"):
                self.logger.info("🔧 Using Redis Cloud optimized connection from REDIS_URL...")

                # Use environment variable instead of hardcoded credentials - SECURE
                # Note: socket_keepalive_options not supported on Windows
                import platform
                keepalive_opts = {}
                if platform.system() != 'Windows':
                    keepalive_opts = {
                        'socket_keepalive_options': {
                            'TCP_KEEPIDLE': 1,
                            'TCP_KEEPINTVL': 3,
                            'TCP_KEEPCNT': 5
                        }
                    }

                self.redis_client = redis.from_url(
                    self.config.redis_url,
                    ssl_cert_reqs='required',
                    decode_responses=False,
                    socket_timeout=self.config.redis_socket_timeout,
                    socket_keepalive=True,
                    socket_connect_timeout=5,
                    **keepalive_opts
                )
            elif self.config.redis_url.startswith(("redis://", "rediss://")):
                # Generic Redis URL with optimizations - fixed
                import platform
                keepalive_opts = {}
                if platform.system() != 'Windows':
                    keepalive_opts = {
                        'socket_keepalive_options': {
                            'TCP_KEEPIDLE': 1,
                            'TCP_KEEPINTVL': 3,
                            'TCP_KEEPCNT': 5
                        }
                    }

                self.redis_client = redis.from_url(
                    self.config.redis_url,
                    socket_timeout=self.config.redis_socket_timeout,
                    socket_keepalive=True,
                    decode_responses=False,
                    socket_connect_timeout=5,
                    **keepalive_opts
                )
            else:
                # Direct host/port configuration
                self.redis_client = redis.Redis(
                    host=self.config.redis_url,
                    port=6379,
                    decode_responses=False,
                    socket_timeout=self.config.redis_socket_timeout,
                )
            
            # Test connection with simpler approach
            await self.redis_client.ping()
            self.logger.info("✅ Redis Cloud connection initialized successfully")
            
            # Test stream operations if configured
            if self.config.redis_cloud_optimized:
                await self._test_redis_cloud_features()
                    
        except Exception as e:
            self.logger.error(f"❌ Redis Cloud initialization failed: {e}")
            self.redis_client = None
    
    async def _test_redis_cloud_features(self):
        """Test Redis Cloud specific features"""
        try:
            # Test stream operations
            test_stream = "test:redis_cloud_init"
            await self.redis_client.xadd(
                test_stream, {"init": "test", "timestamp": str(time.time())}
            )
            
            # Test memory usage (Redis Cloud specific)
            info = await self.redis_client.info('memory')
            used_memory_mb = int(info.get('used_memory', 0)) / (1024 * 1024)
            
            if used_memory_mb > self.config.redis_memory_threshold_mb:
                self.logger.warning(f"⚠️ Redis Cloud memory usage high: {used_memory_mb:.1f}MB")
            
            # Cleanup test data
            await self.redis_client.delete(test_stream)
            self.logger.info("✅ Redis Cloud features test passed")
            
        except Exception as e:
            self.logger.warning(f"⚠️ Redis Cloud features test failed: {e}")
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.aclose()
            self.redis_client = None


class KrakenWebSocketClient:
    """
    Production-grade Kraken WebSocket client with Redis Cloud optimization and fixes
    """
    
    def __init__(self, config: KrakenWSConfig = None):
        # Validate configuration
        if config is None:
            config = KrakenWSConfig()
        elif isinstance(config, dict):
            config = KrakenWSConfig(**config)
        elif not isinstance(config, KrakenWSConfig):
            raise ValueError("Config must be KrakenWSConfig instance or dict")

        self.config = config
        self.logger = logging.getLogger(__name__)

        # Connection state tracking (PRD-001 Section 4.1)
        self.connection_state = ConnectionState.DISCONNECTED
        self.connection_state_changed_at = time.time()  # Track when state changed
        self.reconnection_attempt = 0  # Current reconnection attempt (reset on success) - PRD-001 Section 4.2

        # Resource management
        self.redis_manager = RedisConnectionManager(config)
        self.ws: Optional[websockets.WebSocketServerProtocol] = None
        self.running = False
        self.last_heartbeat = time.time()
        
        # Circuit breakers (Redis Cloud optimized)
        self.circuit_breakers = {
            "spread": CircuitBreaker(
                "spread", self.config.max_consecutive_errors, 
                self.config.circuit_breaker_cooldown
            ),
            "latency": CircuitBreaker(
                "latency", self.config.max_consecutive_errors, 
                self.config.circuit_breaker_cooldown
            ),
            "connection": CircuitBreaker(
                "connection", self.config.max_consecutive_errors, 
                self.config.circuit_breaker_cooldown
            )
        }
        
        # Latency tracking
        self.latency_tracker = LatencyTracker() if config.enable_latency_tracking else None
        
        # Callbacks for different data types
        self.callbacks: Dict[str, List[Callable]] = {
            "trade": [],
            "spread": [],
            "book": [],
            "ohlc": [],
            "ticker": [],
            "circuit_breaker": []
        }
        
        # Statistics and monitoring
        self.stats = {
            "messages_received": 0,
            "reconnects": 0,
            "last_data_time": None,
            "latency_ms": 0,
            "circuit_breaker_trips": 0,
            "errors": 0,
            "trades_per_minute": 0,
            "last_trade_count_reset": time.time()
        }

        # Sequence number tracking per channel (PRD-001 Section 1.3)
        self.last_sequence: Dict[str, int] = {}

        # Message deduplication cache (PRD-001 Section 1.3)
        # Store last 100 message IDs per channel to detect duplicates
        self.dedup_cache: Dict[str, deque] = {}

        # Data cache for graceful degradation (PRD-001 Section 1.4)
        # Store latest data for each channel:pair with timestamp
        # Cache TTL: 5 minutes (300 seconds)
        self.data_cache: Dict[str, Dict[str, Any]] = {}
        self.cache_ttl = 300  # 5 minutes in seconds

        # Scalping rate limiting
        self.trade_timestamps = []
    
    def create_subscription(self, channel: str, pairs: List[str], **kwargs) -> dict:
        """Create a subscription message for Kraken WebSocket"""
        return {
            "event": "subscribe",
            "pair": pairs,
            "subscription": {"name": channel, **kwargs}
        }

    def _set_connection_state(self, new_state: ConnectionState, reason: str = ""):
        """
        Set connection state and log the transition (PRD-001 Section 4.1).

        Args:
            new_state: The new connection state
            reason: Optional reason for the state change
        """
        if self.connection_state != new_state:
            old_state = self.connection_state
            self.connection_state = new_state
            self.connection_state_changed_at = time.time()  # Track timestamp for health check
            timestamp = datetime.now().isoformat()

            # Log state change at INFO level with timestamp (PRD-001 Section 8.1)
            log_msg = f"[{timestamp}] Connection state: {old_state.value} → {new_state.value}"
            if reason:
                log_msg += f" ({reason})"
            self.logger.info(log_msg)

            # Emit Prometheus metric (PRD-001 Section 4.1 & 8.2)
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_CONNECTIONS_TOTAL:
                KRAKEN_WS_CONNECTIONS_TOTAL.labels(state=new_state.value).inc()

    def get_connection_state(self) -> ConnectionState:
        """Get the current connection state"""
        return self.connection_state

    @property
    def is_healthy(self) -> bool:
        """
        Check if bot is healthy based on connection state (PRD-001 Section 4.1 & 4.2).

        Returns False if:
        - WebSocket has been disconnected for > 2 minutes, OR
        - Reconnection attempts have reached or exceeded max_retries
        """
        # Unhealthy if max reconnection attempts reached (PRD-001 Section 4.2)
        if self.reconnection_attempt >= self.config.max_retries:
            return False

        # Unhealthy if not disconnected (connecting, connected, reconnecting are all healthy)
        if self.connection_state != ConnectionState.DISCONNECTED:
            return True

        # Check how long we've been disconnected (2 minutes = 120 seconds)
        time_disconnected = time.time() - self.connection_state_changed_at
        return time_disconnected <= 120

    async def trigger_circuit_breaker(self, breaker_name: str, reason: str):
        """Trigger a circuit breaker"""
        self.stats["circuit_breaker_trips"] += 1
        self.logger.error(f"🚨 Circuit breaker {breaker_name} triggered: {reason}")
        
        # Notify callbacks
        for callback in self.callbacks["circuit_breaker"]:
            try:
                await callback(breaker_name, reason)
            except Exception as e:
                self.logger.error(f"Error in circuit breaker callback: {e}")
    
    async def check_spread_circuit_breaker(self, spread_bps: float, pair: str):
        """Check if spread exceeds maximum allowed"""
        if spread_bps > self.config.max_spread_bps:
            await self.trigger_circuit_breaker(
                "spread", 
                f"{pair} spread {spread_bps:.2f} bps > limit {self.config.max_spread_bps} bps"
            )
            return True
        return False
    
    async def check_latency_circuit_breaker(self, latency_ms: float):
        """Check if latency exceeds maximum allowed"""
        if latency_ms > self.config.max_latency_ms:
            await self.trigger_circuit_breaker(
                "latency", 
                f"Latency {latency_ms:.2f}ms > limit {self.config.max_latency_ms}ms"
            )
            return True
        return False
    
    async def check_scalping_rate_limit(self):
        """Check scalping rate limits"""
        now = time.time()
        
        # Clean old timestamps (older than 1 minute)
        self.trade_timestamps = [ts for ts in self.trade_timestamps if now - ts < 60]
        
        # Check rate limit
        if len(self.trade_timestamps) >= self.config.scalp_max_trades_per_minute:
            await self.trigger_circuit_breaker(
                "scalping_rate", 
                f"Scalping rate limit exceeded: {len(self.trade_timestamps)} trades/min"
            )
            return True
        
        return False
    
    async def setup_subscriptions(self):
        """
        Setup all required subscriptions based on configuration (PRD-001 Section 4.1).

        This method is called on every successful connection, including reconnections.
        It automatically resubscribes to all channels after a reconnection (PRD-001 Section 4.2).
        """
        subscriptions = []

        # Log subscription setup - distinguish initial vs resubscription (PRD-001 Section 4.2)
        is_reconnection = self.reconnection_attempt > 0 or self.stats["reconnects"] > 0
        if is_reconnection:
            self.logger.info(
                f"Resubscribing to all channels after reconnection for {len(self.config.pairs)} pairs: "
                f"{', '.join(self.config.pairs)}"
            )
        else:
            self.logger.info(
                f"Setting up initial Kraken WS subscriptions for {len(self.config.pairs)} pairs: "
                f"{', '.join(self.config.pairs)}"
            )

        # Ticker data for all pairs (PRD-001 Section 4.1)
        subscriptions.append(
            self.create_subscription("ticker", self.config.pairs)
        )

        # Trade data for all pairs
        subscriptions.append(
            self.create_subscription("trade", self.config.pairs)
        )

        # Spread data for all pairs
        subscriptions.append(
            self.create_subscription("spread", self.config.pairs)
        )

        # Order book data (L2, configurable depth) (PRD-001 Section 4.1)
        subscriptions.append(
            self.create_subscription(
                "book",
                self.config.pairs,
                depth=self.config.book_depth
            )
        )
        
        # OHLC data for configured timeframes
        for timeframe in self.config.timeframes:
            if timeframe in ["15s", "1m", "3m", "5m", "15m", "30m", "1h", "4h", "1d"]:
                # Convert timeframe to Kraken format
                kraken_interval = {
                    "15s": 15, "1m": 1, "3m": 3, "5m": 5, "15m": 15,
                    "30m": 30, "1h": 60, "4h": 240, "1d": 1440
                }.get(timeframe)
                
                if kraken_interval:
                    subscriptions.append(
                        self.create_subscription(
                            "ohlc", 
                            self.config.pairs, 
                            interval=kraken_interval
                        )
                    )
        
        # Send all subscriptions with circuit breaker protection
        sent_count = 0
        for sub in subscriptions:
            try:
                await self.circuit_breakers["connection"].call(
                    self.ws.send, json.dumps(sub)
                )
                self.logger.debug(f"Sent subscription: {sub}")
                sent_count += 1
                await asyncio.sleep(0.1)  # Rate limiting
            except Exception as e:
                self.logger.error(f"Failed to send subscription {sub}: {e}")  # PRD-001 Section 1.4
                # Emit Prometheus counter (PRD-001 Section 1.4)
                if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                    KRAKEN_WS_ERRORS_TOTAL.labels(error_type='subscription').inc()

        # Log subscription completion at INFO level (PRD-001 Section 8.1 & 4.2)
        if is_reconnection:
            self.logger.info(
                f"Resubscription complete: {sent_count}/{len(subscriptions)} channels successfully resubscribed "
                f"(ticker, spread, trade, book)"
            )
        else:
            self.logger.info(
                f"Initial subscriptions complete: {sent_count}/{len(subscriptions)} sent successfully"
            )
    
    async def handle_trade_data(self, channel_id: int, data: List, channel: str, pair: str):
        """Handle trade data with enhanced logging and debugging"""
        operation_id = f"trade_{channel_id}_{time.time()}"
        
        if self.latency_tracker:
            self.latency_tracker.start_timing(operation_id)
        
        try:
            trades = []
            self.logger.debug(f"🔄 Processing {len(data)} trade records for {pair}")
            
            for i, trade_data in enumerate(data):
                try:
                    if len(trade_data) < 5:
                        self.logger.warning(f"⚠️ Incomplete trade data at index {i}: {trade_data}")
                        continue
                    
                    trade = {
                        "pair": pair,
                        "price": float(trade_data[0]),
                        "volume": float(trade_data[1]),
                        "timestamp": float(trade_data[2]),
                        "side": trade_data[3],  # 'b' for buy, 's' for sell
                        "order_type": trade_data[4],  # 'l' for limit, 'm' for market
                        "misc": trade_data[5] if len(trade_data) > 5 else "",
                        "received_at": time.time()
                    }
                    trades.append(trade)
                    
                    # Log significant trades
                    if trade["volume"] >= 0.01:  # Log trades >= 0.01 BTC
                        self.logger.info(
                            f"💰 {pair} Trade: {trade['side'].upper()} "
                            f"{trade['volume']:.4f} @ ${trade['price']:.2f}"
                        )
                    
                    # Check scalping volume threshold
                    if (self.config.scalp_enabled and 
                        trade["volume"] >= self.config.scalp_min_volume):
                        self.trade_timestamps.append(trade["received_at"])
                        
                except (ValueError, IndexError) as e:
                    self.logger.warning(f"⚠️ Error parsing trade data at index {i}: {e}")
                    continue
            
            if not trades:
                self.logger.warning(f"⚠️ No valid trades parsed from {len(data)} records for {pair}")
                return

            # Cache data for graceful degradation (PRD-001 Section 1.4)
            self.cache_data(channel, pair, trades)

            # Check scalping rate limits
            if self.config.scalp_enabled:
                await self.check_scalping_rate_limit()

            # Stream to Redis only if available - with better error handling
            if self.redis_manager.redis_client:
                try:
                    async with self.redis_manager.get_connection() as redis_conn:
                        # Shard by pair for scalability
                        stream_name = (
                            f"{self.config.redis_streams['trade']}:"
                            f"{pair.replace('/', '-')}"
                        )
                        
                        # Redis Cloud optimized data structure
                        stream_data = {
                            "channel": "trade",
                            "pair": pair,
                            "trades": orjson.dumps(trades).decode('utf-8'),
                            "timestamp": str(time.time()),
                            "shard": pair.replace('/', '-'),
                            "batch_size": str(len(trades)),
                            "redis_optimized": "true"
                        }
                        
                        # Use Redis Cloud optimized stream operations
                        await redis_conn.xadd(
                            stream_name, 
                            stream_data, 
                            maxlen=self.config.redis_memory_threshold_mb * 10
                        )
                        self.logger.debug(
                            f"✅ Stored {len(trades)} trades to Redis stream {stream_name}"
                        )
                        
                except Exception as e:
                    # Redis Cloud specific error handling
                    if "MAXMEMORY" in str(e) or "OOM" in str(e):
                        self.logger.warning(f"Redis Cloud memory limit reached: {e}")
                    else:
                        self.logger.debug(f"Redis write failed (non-critical): {e}")
            
            # Call registered callbacks
            for callback in self.callbacks["trade"]:
                try:
                    await callback(pair, trades)
                except Exception as e:
                    self.logger.error(f"Error in trade callback: {e}")
            
            # Update statistics
            self.stats["messages_received"] += 1
            self.logger.debug(f"📈 Processed {len(trades)} trades for {pair}")
            
        except Exception as e:
            self.stats["errors"] += 1
            self.logger.error(f"Error handling trade data: {e}")
            # Don't raise - continue processing
        finally:
            if self.latency_tracker:
                latency_ms = self.latency_tracker.end_timing(operation_id)
                self.stats["latency_ms"] = latency_ms
                await self.check_latency_circuit_breaker(latency_ms)
    
    async def handle_spread_data(self, channel_id: int, data: List, channel: str, pair: str):
        """Handle spread data with circuit breaker for wide spreads"""
        operation_id = f"spread_{channel_id}_{time.time()}"
        
        if self.latency_tracker:
            self.latency_tracker.start_timing(operation_id)
        
        try:
            spread_info = {
                "pair": pair,
                "bid": float(data[0]),
                "ask": float(data[1]),
                "timestamp": float(data[2]),
                "bid_volume": float(data[3]),
                "ask_volume": float(data[4]),
                "received_at": time.time()
            }
            
            # Calculate spread in basis points
            spread_bps = ((spread_info["ask"] - spread_info["bid"]) / spread_info["bid"]) * 10000
            spread_info["spread_bps"] = spread_bps

            # Cache data for graceful degradation (PRD-001 Section 1.4)
            self.cache_data(channel, pair, spread_info)

            # Check spread circuit breaker
            await self.check_spread_circuit_breaker(spread_bps, pair)

            # Stream to Redis only if available - Redis Cloud optimized
            if self.redis_manager.redis_client:
                try:
                    async with self.redis_manager.get_connection() as redis_conn:
                        stream_name = (
                            f"{self.config.redis_streams['spread']}:"
                            f"{pair.replace('/', '-')}"
                        )
                        
                        stream_data = {
                            "channel": "spread",
                            "pair": pair,
                            "data": orjson.dumps(spread_info).decode('utf-8'),
                            "timestamp": str(time.time()),
                            "spread_bps": str(spread_bps),
                            "shard": pair.replace('/', '-')
                        }
                        
                        await redis_conn.xadd(stream_name, stream_data, maxlen=5000)
                except Exception as e:
                    if "MAXMEMORY" in str(e) or "OOM" in str(e):
                        self.logger.warning(f"Redis Cloud memory limit reached: {e}")
                    else:
                        self.logger.debug(f"Redis write failed (non-critical): {e}")
            
            # Call registered callbacks
            for callback in self.callbacks["spread"]:
                try:
                    await callback(pair, spread_info)
                except Exception as e:
                    self.logger.error(f"Error in spread callback: {e}")
            
        except Exception as e:
            self.stats["errors"] += 1
            self.logger.error(f"Error handling spread data: {e}")
            # Don't raise - continue processing
        finally:
            if self.latency_tracker:
                latency_ms = self.latency_tracker.end_timing(operation_id)
                await self.check_latency_circuit_breaker(latency_ms)
    
    async def handle_book_data(self, channel_id: int, data: dict, channel: str, pair: str):
        """Handle order book data - Redis Cloud optimized"""
        operation_id = f"book_{channel_id}_{time.time()}"
        
        if self.latency_tracker:
            self.latency_tracker.start_timing(operation_id)
        
        try:
            book_data = {
                "pair": pair,
                "bids": [[float(price), float(volume), float(timestamp)]
                        for price, volume, timestamp in data.get("bs", [])],
                "asks": [[float(price), float(volume), float(timestamp)]
                        for price, volume, timestamp in data.get("as", [])],
                "checksum": data.get("c"),
                "received_at": time.time()
            }

            # Cache data for graceful degradation (PRD-001 Section 1.4)
            self.cache_data(channel, pair, book_data)

            # Stream to Redis only if available - Redis Cloud optimized
            if self.redis_manager.redis_client:
                try:
                    async with self.redis_manager.get_connection() as redis_conn:
                        stream_name = (
                            f"{self.config.redis_streams['book']}:"
                            f"{pair.replace('/', '-')}"
                        )
                        
                        stream_data = {
                            "channel": "book",
                            "pair": pair,
                            "data": orjson.dumps(book_data).decode('utf-8'),
                            "timestamp": str(time.time()),
                            "shard": pair.replace('/', '-')
                        }
                        
                        await redis_conn.xadd(stream_name, stream_data, maxlen=3000)
                except Exception as e:
                    if "MAXMEMORY" in str(e) or "OOM" in str(e):
                        self.logger.warning(f"Redis Cloud memory limit reached: {e}")
                    else:
                        self.logger.debug(f"Redis write failed (non-critical): {e}")
            
            # Call registered callbacks
            for callback in self.callbacks["book"]:
                try:
                    await callback(pair, book_data)
                except Exception as e:
                    self.logger.error(f"Error in book callback: {e}")
            
        except Exception as e:
            self.stats["errors"] += 1
            self.logger.error(f"Error handling book data: {e}")
            # Don't raise - continue processing
        finally:
            if self.latency_tracker:
                latency_ms = self.latency_tracker.end_timing(operation_id)
                await self.check_latency_circuit_breaker(latency_ms)
    
    async def handle_ohlc_data(self, channel_id: int, data: List, channel: str, pair: str):
        """Handle OHLC/candlestick data with safe parsing - Redis Cloud optimized"""
        operation_id = f"ohlc_{channel_id}_{time.time()}"
        
        if self.latency_tracker:
            self.latency_tracker.start_timing(operation_id)
        
        try:
            # Validate data structure - OHLC data should have at least 10 elements
            if not isinstance(data, list) or len(data) < 10:
                self.logger.debug(
                    f"Invalid OHLC data structure for {pair}: "
                    f"{len(data) if isinstance(data, list) else 'not list'} elements"
                )
                return
            
            ohlc = {
                "pair": pair,
                "time": float(data[1]) if len(data) > 1 else 0,
                "etime": float(data[2]) if len(data) > 2 else 0,
                "open": float(data[3]) if len(data) > 3 else 0,
                "high": float(data[4]) if len(data) > 4 else 0,
                "low": float(data[5]) if len(data) > 5 else 0,
                "close": float(data[6]) if len(data) > 6 else 0,
                "vwap": float(data[7]) if len(data) > 7 else 0,
                "volume": float(data[8]) if len(data) > 8 else 0,
                "count": int(data[9]) if len(data) > 9 else 0,
                "received_at": time.time()
            }

            # Cache data for graceful degradation (PRD-001 Section 1.4)
            self.cache_data(channel, pair, ohlc)

            # Stream to Redis only if available - Redis Cloud optimized
            if self.redis_manager.redis_client:
                try:
                    async with self.redis_manager.get_connection() as redis_conn:
                        stream_name = (
                            f"{self.config.redis_streams['ohlc']}:"
                            f"{pair.replace('/', '-')}"
                        )
                        
                        stream_data = {
                            "channel": "ohlc",
                            "pair": pair,
                            "data": orjson.dumps(ohlc).decode('utf-8'),
                            "timestamp": str(time.time()),
                            "shard": pair.replace('/', '-')
                        }
                        
                        await redis_conn.xadd(stream_name, stream_data, maxlen=2000)
                except Exception as e:
                    if "MAXMEMORY" in str(e) or "OOM" in str(e):
                        self.logger.warning(f"Redis Cloud memory limit reached: {e}")
                    else:
                        self.logger.debug(f"Redis write failed (non-critical): {e}")
            
            # Call registered callbacks
            for callback in self.callbacks["ohlc"]:
                try:
                    await callback(pair, ohlc)
                except Exception as e:
                    self.logger.error(f"Error in ohlc callback: {e}")
            
        except (ValueError, IndexError) as e:
            self.logger.debug(f"Error parsing OHLC data for {pair}: {e}")
        except Exception as e:
            self.stats["errors"] += 1
            self.logger.error(f"Error handling OHLC data: {e}")
            # Don't raise - continue processing
        finally:
            if self.latency_tracker:
                latency_ms = self.latency_tracker.end_timing(operation_id)
                await self.check_latency_circuit_breaker(latency_ms)
    
    async def handle_subscription_status(self, data: dict):
        """Handle subscription confirmation messages"""
        status = data.get("status")
        subscription = data.get("subscription", {})
        channel = subscription.get("name")
        
        if status == "subscribed":
            self.logger.info(f"✅ Subscribed to {channel}")
        elif status == "error":
            error_msg = data.get("errorMessage", "Unknown error")
            self.logger.error(f"❌ Subscription error for {channel}: {error_msg}")
    
    def validate_message_schema(self, data) -> tuple[bool, str]:
        """
        Validate Kraken message schema (PRD-001 Section 1.3).

        Returns:
            tuple[bool, str]: (is_valid, error_message)
        """
        # Event messages (dict) are valid - they have different schema
        if isinstance(data, dict):
            return True, ""

        # Data messages must be arrays with at least 4 elements (PRD-001 Section 1.3)
        if not isinstance(data, list):
            return False, f"Invalid message type: expected list or dict, got {type(data).__name__}"

        if len(data) < 4:
            return False, f"Invalid message length: expected >= 4, got {len(data)}"

        # Check required fields: channel_id (int), payload (dict/list), channel (str), pair (str)
        channel_id = data[0]
        payload = data[1]
        channel = data[2]
        pair = data[3]

        # Validate channel_id is numeric
        if not isinstance(channel_id, (int, float)):
            return False, f"Invalid channel_id type: expected int, got {type(channel_id).__name__}"

        # Validate payload is dict or list
        if not isinstance(payload, (dict, list)):
            return False, f"Invalid payload type: expected dict or list, got {type(payload).__name__}"

        # Validate channel is string
        if not isinstance(channel, str):
            return False, f"Invalid channel type: expected str, got {type(channel).__name__}"

        # Validate pair is string
        if not isinstance(pair, str):
            return False, f"Invalid pair type: expected str, got {type(pair).__name__}"

        # All validations passed
        return True, ""

    def extract_and_validate_sequence(self, data: list, channel: str, pair: str) -> None:
        """
        Extract and validate sequence numbers from Kraken messages (PRD-001 Section 1.3).

        Tracks last sequence number per channel and detects gaps.
        Currently, sequence numbers are primarily found in book (order book) messages.
        """
        # Only list messages can have sequence numbers
        if not isinstance(data, list) or len(data) < 2:
            return

        payload = data[1]

        # Extract sequence number from payload (if available)
        sequence = None

        # For book messages, sequence may be in the payload dict
        if isinstance(payload, dict):
            # Try different possible sequence field names
            sequence = payload.get("s") or payload.get("sequence")

        # If we found a sequence number, validate it
        if sequence is not None:
            try:
                sequence = int(sequence)
            except (ValueError, TypeError):
                self.logger.warning(f"Invalid sequence number format for {channel}/{pair}: {sequence}")
                return

            # Create unique key for this channel/pair combination
            channel_key = f"{channel}:{pair}"

            # Check for sequence gaps (PRD-001 Section 1.3)
            if channel_key in self.last_sequence:
                last_seq = self.last_sequence[channel_key]
                expected_seq = last_seq + 1

                if sequence != expected_seq:
                    gap = sequence - last_seq
                    self.logger.warning(
                        f"Sequence gap detected for {channel}/{pair}: "
                        f"expected {expected_seq}, got {sequence} (gap: {gap})"
                    )

                    # Emit Prometheus counter for sequence gaps (PRD-001 Section 1.3)
                    if PROMETHEUS_AVAILABLE and KRAKEN_WS_MESSAGE_GAPS_TOTAL:
                        KRAKEN_WS_MESSAGE_GAPS_TOTAL.labels(channel=channel).inc()

            # Update last sequence for this channel
            self.last_sequence[channel_key] = sequence

    def validate_message_timestamp(self, data: list, channel: str) -> tuple[bool, str]:
        """
        Validate message timestamp (PRD-001 Section 1.3).

        Rejects messages that are:
        - More than 5 seconds old (stale data protection)
        - More than 5 seconds in the future (clock skew protection)

        Returns:
            tuple[bool, str]: (is_valid, rejection_reason)
        """
        # Only list messages can have timestamps
        if not isinstance(data, list) or len(data) < 2:
            return True, ""

        payload = data[1]
        timestamp = None

        # Extract timestamp from payload
        # Different message types have timestamps in different locations
        if isinstance(payload, dict):
            # Book messages might have timestamp in the dict
            timestamp = payload.get("timestamp") or payload.get("ts") or payload.get("time")
        elif isinstance(payload, list) and len(payload) > 0:
            # Trade/OHLC messages often have timestamp as last element in each trade
            # Try to find a timestamp field
            for item in payload:
                if isinstance(item, dict):
                    timestamp = item.get("timestamp") or item.get("ts") or item.get("time")
                    if timestamp:
                        break

        # If we found a timestamp, validate it
        if timestamp is not None:
            try:
                # Convert to float if it's a string
                if isinstance(timestamp, str):
                    message_time = float(timestamp)
                else:
                    message_time = float(timestamp)

                current_time = time.time()
                time_delta = current_time - message_time

                # Reject if more than 5 seconds old (stale data)
                if time_delta > 5.0:
                    reason = f"stale (age: {time_delta:.2f}s)"
                    self.logger.warning(
                        f"Rejecting stale message for {channel}: "
                        f"timestamp {message_time:.2f}, current {current_time:.2f}, "
                        f"delta {time_delta:.2f}s"
                    )

                    # Emit Prometheus counter (PRD-001 Section 1.3)
                    if PROMETHEUS_AVAILABLE and KRAKEN_WS_STALE_MESSAGES_TOTAL:
                        KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel=channel, reason='stale').inc()

                    return False, reason

                # Reject if more than 5 seconds in the future (clock skew)
                if time_delta < -5.0:
                    reason = f"future (delta: {abs(time_delta):.2f}s)"
                    self.logger.warning(
                        f"Rejecting future-dated message for {channel}: "
                        f"timestamp {message_time:.2f}, current {current_time:.2f}, "
                        f"delta {time_delta:.2f}s"
                    )

                    # Emit Prometheus counter (PRD-001 Section 1.3)
                    if PROMETHEUS_AVAILABLE and KRAKEN_WS_STALE_MESSAGES_TOTAL:
                        KRAKEN_WS_STALE_MESSAGES_TOTAL.labels(channel=channel, reason='future').inc()

                    return False, reason

            except (ValueError, TypeError) as e:
                self.logger.debug(f"Could not parse timestamp for {channel}: {e}")
                # Don't reject on parse errors - might not be a timestamp field

        # No timestamp found or timestamp is valid
        return True, ""

    def generate_message_id(self, data: list, channel: str, pair: str) -> str:
        """
        Generate unique message ID for deduplication (PRD-001 Section 1.3).

        Creates ID from: channel + pair + timestamp + sequence + payload hash

        Returns:
            str: Unique message ID
        """
        if not isinstance(data, list) or len(data) < 2:
            return ""

        payload = data[1]

        # Start with channel and pair
        id_parts = [channel, pair]

        # Add timestamp if available
        if isinstance(payload, dict):
            timestamp = payload.get("timestamp") or payload.get("ts") or payload.get("time")
            if timestamp:
                id_parts.append(str(timestamp))

            # Add sequence if available
            sequence = payload.get("s") or payload.get("sequence")
            if sequence:
                id_parts.append(str(sequence))

        # Add a hash of the payload for uniqueness
        # Use a simple string representation to keep it lightweight
        payload_str = str(payload)[:100]  # First 100 chars to keep it manageable
        id_parts.append(str(hash(payload_str)))

        return ":".join(id_parts)

    def cache_data(self, channel: str, pair: str, data: Any) -> None:
        """
        Cache latest data for graceful degradation (PRD-001 Section 1.4).

        Stores data with timestamp for 5-minute TTL.

        Args:
            channel: Channel name (e.g., 'trade', 'spread', 'ticker', 'book')
            pair: Trading pair (e.g., 'BTC/USD')
            data: Data to cache
        """
        cache_key = f"{channel}:{pair}"
        self.data_cache[cache_key] = {
            "data": data,
            "timestamp": time.time(),
            "channel": channel,
            "pair": pair
        }
        self.logger.debug(f"Cached data for {cache_key}")

    def get_cached_data(self, channel: str, pair: str) -> Optional[Dict[str, Any]]:
        """
        Get cached data if available and not stale (PRD-001 Section 1.4).

        Returns cached data only if:
        - Cache entry exists
        - Cache age < TTL (5 minutes)
        - WebSocket has been unavailable > 30 seconds

        Args:
            channel: Channel name
            pair: Trading pair

        Returns:
            Cached data dict with 'data', 'timestamp', 'age' keys, or None
        """
        cache_key = f"{channel}:{pair}"

        # Check if we have cached data
        if cache_key not in self.data_cache:
            return None

        cached = self.data_cache[cache_key]
        cache_age = time.time() - cached["timestamp"]

        # Check if cache is still valid (< 5 minutes old)
        if cache_age > self.cache_ttl:
            self.logger.debug(f"Cache expired for {cache_key} (age: {cache_age:.1f}s)")
            return None

        # Only serve cached data if WebSocket has been unavailable > 30 seconds
        time_since_connection = time.time() - self.connection_state_changed_at
        if self.connection_state == ConnectionState.CONNECTED or time_since_connection < 30:
            return None  # Don't serve cache if recently connected

        self.logger.info(
            f"Serving cached data for {cache_key} "
            f"(age: {cache_age:.1f}s, disconnected: {time_since_connection:.1f}s)"
        )

        return {
            "data": cached["data"],
            "timestamp": cached["timestamp"],
            "age": cache_age,
            "cached": True
        }

    def is_cache_valid(self, channel: str, pair: str) -> bool:
        """
        Check if cached data exists and is valid (PRD-001 Section 1.4).

        Args:
            channel: Channel name
            pair: Trading pair

        Returns:
            True if cache exists and age < TTL (5 minutes)
        """
        cache_key = f"{channel}:{pair}"

        if cache_key not in self.data_cache:
            return False

        cache_age = time.time() - self.data_cache[cache_key]["timestamp"]
        return cache_age <= self.cache_ttl

    def check_duplicate(self, data: list, channel: str, pair: str) -> bool:
        """
        Check if message is a duplicate (PRD-001 Section 1.3).

        Maintains a cache of last 100 message IDs per channel.

        Returns:
            bool: True if duplicate, False if new message
        """
        # Generate message ID
        msg_id = self.generate_message_id(data, channel, pair)

        if not msg_id:
            return False  # Can't determine, assume not duplicate

        # Get or create dedup cache for this channel
        channel_key = f"{channel}:{pair}"
        if channel_key not in self.dedup_cache:
            self.dedup_cache[channel_key] = deque(maxlen=100)

        # Check if message ID is in cache
        if msg_id in self.dedup_cache[channel_key]:
            # Duplicate detected!
            self.logger.warning(f"Duplicate message detected for {channel}/{pair}: {msg_id}")

            # Emit Prometheus counter (PRD-001 Section 1.3)
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_DUPLICATES_REJECTED_TOTAL:
                KRAKEN_WS_DUPLICATES_REJECTED_TOTAL.labels(channel=channel).inc()

            return True

        # Not a duplicate - add to cache
        self.dedup_cache[channel_key].append(msg_id)
        return False

    async def handle_message(self, message: str):
        """Handle incoming WebSocket messages with enhanced debugging and validation (PRD-001 Section 1.3)"""
        message_start_time = time.time()

        try:
            data = json.loads(message)
            self.stats["messages_received"] += 1
            self.stats["last_data_time"] = time.time()

            # Enhanced logging for debugging
            if isinstance(data, dict):
                event_type = data.get("event", "unknown")
                self.logger.debug(f"📨 Received event: {event_type}")

                if data.get("event") == "subscriptionStatus":
                    await self.handle_subscription_status(data)
                elif data.get("event") == "systemStatus":
                    status = data.get("status")
                    self.logger.info(f"Kraken system status: {status}")
                elif data.get("event") == "heartbeat":
                    self.last_heartbeat = time.time()
                    self.logger.debug("💓 Heartbeat received")
                return

            # Validate message schema (PRD-001 Section 1.3)
            is_valid, error_msg = self.validate_message_schema(data)
            if not is_valid:
                self.logger.warning(f"Invalid message schema: {error_msg}")
                self.stats["errors"] += 1
                return

            # Handle data messages (arrays) with enhanced logging
            if isinstance(data, list) and len(data) >= 4:
                channel_id = data[0]
                payload = data[1]
                channel = data[2]
                pair = data[3]

                # Extract and validate sequence numbers (PRD-001 Section 1.3)
                self.extract_and_validate_sequence(data, channel, pair)

                # Validate message timestamp (PRD-001 Section 1.3)
                is_valid_timestamp, rejection_reason = self.validate_message_timestamp(data, channel)
                if not is_valid_timestamp:
                    self.logger.debug(f"Message rejected due to timestamp: {rejection_reason}")
                    self.stats["errors"] += 1
                    return

                # Check for duplicate messages (PRD-001 Section 1.3)
                if self.check_duplicate(data, channel, pair):
                    self.logger.debug(f"Message rejected: duplicate")
                    self.stats["errors"] += 1
                    return

                # Log the message type for debugging
                self.logger.debug(f"📊 Received {channel} data for {pair} (items: {len(payload) if isinstance(payload, list) else 'dict'})")

                # Route to appropriate handler with circuit breaker protection
                try:
                    if channel.startswith("trade"):
                        await self.circuit_breakers["connection"].call(
                            self.handle_trade_data, channel_id, payload, channel, pair
                        )
                    elif channel.startswith("spread"):
                        await self.circuit_breakers["spread"].call(
                            self.handle_spread_data, channel_id, payload, channel, pair
                        )
                    elif channel.startswith("book"):
                        await self.circuit_breakers["connection"].call(
                            self.handle_book_data, channel_id, payload, channel, pair
                        )
                    elif channel.startswith("ohlc"):
                        await self.circuit_breakers["connection"].call(
                            self.handle_ohlc_data, channel_id, payload, channel, pair
                        )
                    else:
                        self.logger.debug(f"🤷 Unknown channel type: {channel}")
                except Exception as e:
                    self.logger.error(f"Handler error for {channel}: {e}")
                    # Emit Prometheus counter (PRD-001 Section 1.4)
                    if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                        KRAKEN_WS_ERRORS_TOTAL.labels(error_type='handler_error').inc()
                    # Don't raise - continue processing other messages
            else:
                self.logger.debug(f"📋 Received data structure: {type(data)} with length {len(data) if hasattr(data, '__len__') else 'unknown'}")

        except json.JSONDecodeError as e:
            self.stats["errors"] += 1
            self.logger.warning(f"Message parsing error: {e}")  # PRD-001 Section 1.4: WARNING level for parsing errors
            self.logger.debug(f"Raw message: {message[:200]}...")  # First 200 chars for debugging
            # Emit Prometheus counter (PRD-001 Section 1.4)
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                KRAKEN_WS_ERRORS_TOTAL.labels(error_type='json_decode').inc()
        except Exception as e:
            self.stats["errors"] += 1
            self.logger.error(f"Error handling message: {e}")
            # Emit Prometheus counter (PRD-001 Section 1.4)
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                KRAKEN_WS_ERRORS_TOTAL.labels(error_type='message_handling').inc()
            # Don't raise - continue processing
        finally:
            # Track message processing latency
            if self.latency_tracker:
                processing_time = (time.time() - message_start_time) * 1000
                if processing_time > 10:  # Log slow message processing
                    self.logger.warning(f"Slow message processing: {processing_time:.2f}ms")
    
    def register_callback(self, channel: str, callback: Callable):
        """Register a callback for specific channel data"""
        if channel in self.callbacks:
            self.callbacks[channel].append(callback)
        else:
            self.logger.warning(f"Unknown channel: {channel}")
    
    async def _get_redis_cloud_health(self) -> Dict[str, Any]:
        """Get Redis Cloud specific health metrics"""
        health = {
            "connected": False,
            "memory_usage_mb": 0,
            "memory_usage_percent": 0,
            "connection_count": 0,
            "latency_ms": 0
        }
        
        if not self.redis_manager.redis_client:
            return health
        
        try:
            start_time = time.time()
            
            # Test connection and measure latency
            await self.redis_manager.redis_client.ping()
            health["latency_ms"] = (time.time() - start_time) * 1000
            health["connected"] = True
            
            # Get memory info
            info = await self.redis_manager.redis_client.info('memory')
            health["memory_usage_mb"] = int(info.get('used_memory', 0)) / (1024 * 1024)
            
            # Estimate percentage (Redis Cloud typically has 100MB limit)
            health["memory_usage_percent"] = (health["memory_usage_mb"] / self.config.redis_memory_threshold_mb) * 100
            
            # Get connection info
            client_info = await self.redis_manager.redis_client.info('clients')
            health["connection_count"] = int(client_info.get('connected_clients', 0))
            
        except Exception as e:
            self.logger.debug(f"Redis Cloud health check failed: {e}")
        
        return health
    
    async def monitor_health(self):
        """Enhanced health monitoring with Redis Cloud specific metrics"""
        while self.running:
            try:
                current_time = time.time()

                # Check overall health status (PRD-001 Section 4.1)
                if not self.is_healthy:
                    time_disconnected = current_time - self.connection_state_changed_at
                    self.logger.warning(
                        f"⚠️ Bot unhealthy: WebSocket disconnected for {time_disconnected:.1f}s (> 2 minutes)"
                    )

                # Check heartbeat and PONG timeout (PRD-001 Section 4.1)
                time_since_heartbeat = current_time - self.last_heartbeat
                if time_since_heartbeat > 60:
                    self.logger.warning(
                        f"⚠️ Connection timeout: No PONG/heartbeat for {time_since_heartbeat:.1f}s (> 60s)"
                    )

                    # Close WebSocket to trigger reconnection (PRD-001 Section 4.1)
                    if self.ws and self.connection_state == ConnectionState.CONNECTED:
                        self.logger.warning("Closing WebSocket due to PONG timeout, will reconnect...")
                        try:
                            await self.ws.close()
                        except Exception as close_error:
                            self.logger.error(f"Error closing WebSocket: {close_error}")

                # Check data flow
                if self.stats["last_data_time"]:
                    time_since_data = current_time - self.stats["last_data_time"]
                    if time_since_data > 30:
                        self.logger.warning(f"No data received for {time_since_data:.1f}s")
                
                # Calculate trades per minute
                recent_trades = len([ts for ts in self.trade_timestamps if current_time - ts < 60])
                self.stats["trades_per_minute"] = recent_trades
                
                # Get latency statistics
                latency_stats = self.latency_tracker.get_stats() if self.latency_tracker else {}
                
                # Circuit breaker statuses
                cb_statuses = {name: cb.state.value for name, cb in self.circuit_breakers.items()}
                
                # Redis Cloud specific health metrics
                redis_health = await self._get_redis_cloud_health()
                
                # Emit comprehensive health metrics to Redis
                if self.redis_manager.redis_client:
                    try:
                        async with self.redis_manager.get_connection() as redis_conn:
                            health_data = {
                                "timestamp": str(current_time),
                                "is_healthy": str(self.is_healthy),  # PRD-001 Section 4.1
                                "connection_state": self.connection_state.value,  # PRD-001 Section 4.1
                                "messages_received": str(self.stats["messages_received"]),
                                "reconnects": str(self.stats["reconnects"]),
                                "time_since_heartbeat": str(time_since_heartbeat),
                                "running": str(self.running),
                                "errors": str(self.stats["errors"]),
                                "trades_per_minute": str(self.stats["trades_per_minute"]),
                                "circuit_breaker_trips": str(self.stats["circuit_breaker_trips"]),
                                **{f"latency_{k}": str(v) for k, v in latency_stats.items()},
                                **{f"cb_{k}": v for k, v in cb_statuses.items()},
                                # Redis Cloud health metrics
                                **{f"redis_{k}": str(v) for k, v in redis_health.items()}
                            }
                            # Use smaller max length for Redis Cloud
                            await redis_conn.xadd("kraken:health", health_data, maxlen=1000)
                    except Exception as e:
                        self.logger.error(f"Failed to emit health metrics: {e}")
                
                # Adaptive monitoring interval based on Redis Cloud performance
                sleep_interval = self.config.metrics_interval
                if redis_health.get('memory_usage_percent', 0) > 80:
                    # Monitor more frequently if memory high
                    sleep_interval = max(5, sleep_interval // 2)
                
                await asyncio.sleep(sleep_interval)
                
            except Exception as e:
                self.logger.error(f"Error in health monitor: {e}")
                await asyncio.sleep(self.config.metrics_interval)

    async def connect_once(self):
        """Single connection attempt with circuit breaker protection"""
        try:
            # Set state to CONNECTING (PRD-001 Section 4.1)
            self._set_connection_state(ConnectionState.CONNECTING, "Starting connection attempt")
            self.logger.info(f"Kraken WS connecting to {self.config.url}")

            async with websockets.connect(
                self.config.url,
                ping_interval=self.config.ping_interval,
                ping_timeout=self.config.ping_timeout,  # PRD-001 Section 4.1: PONG timeout detection
                close_timeout=self.config.close_timeout,
                compression=None  # Kraken doesn't support compression
            ) as ws:
                self.ws = ws

                # Set state to CONNECTED (PRD-001 Section 4.1)
                self._set_connection_state(ConnectionState.CONNECTED, "WebSocket connection established")
                self.logger.info("Kraken WS connected")

                # Setup subscriptions
                await self.setup_subscriptions()
                
                # Start health monitoring if enabled
                health_task = None
                if self.config.enable_health_monitoring:
                    health_task = asyncio.create_task(self.monitor_health())
                
                try:
                    # Main message loop
                    async for message in ws:
                        if isinstance(message, (bytes, bytearray)):
                            message = message.decode('utf-8')
                        await self.handle_message(message)
                        
                except websockets.exceptions.ConnectionClosed as e:
                    # Handle WebSocket protocol errors (PRD-001 Section 1.4)
                    close_code = e.code if hasattr(e, 'code') else None
                    close_reason = e.reason if hasattr(e, 'reason') else "Unknown"

                    # Log based on close code
                    if close_code == 1000:
                        # Normal closure
                        self.logger.info(f"Kraken WS closed normally (code 1000): {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, "Normal closure")
                    elif close_code == 1001:
                        # Going away
                        self.logger.info(f"Kraken WS endpoint going away (code 1001): {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, "Endpoint going away")
                    elif close_code == 1006:
                        # Abnormal closure (connection lost)
                        self.logger.warning(f"Kraken WS abnormal closure (code 1006): {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, "Abnormal closure - connection lost")
                        # Emit error counter for abnormal closures
                        if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                            KRAKEN_WS_ERRORS_TOTAL.labels(error_type='protocol_error_1006').inc()
                    elif close_code == 1011:
                        # Server error
                        self.logger.error(f"Kraken WS server error (code 1011): {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, "Server error")
                        if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                            KRAKEN_WS_ERRORS_TOTAL.labels(error_type='protocol_error_1011').inc()
                    elif close_code == 1012:
                        # Service restart
                        self.logger.info(f"Kraken WS service restarting (code 1012): {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, "Service restart")
                    else:
                        # Other close codes
                        self.logger.warning(f"Kraken WS closed with code {close_code}: {close_reason}")
                        self._set_connection_state(ConnectionState.DISCONNECTED, f"Closed with code {close_code}")
                        if close_code and close_code >= 1002:  # Error codes start at 1002
                            if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                                KRAKEN_WS_ERRORS_TOTAL.labels(error_type=f'protocol_error_{close_code}').inc()
                finally:
                    if health_task:
                        health_task.cancel()
                        try:
                            await health_task
                        except asyncio.CancelledError:
                            pass

        except websockets.exceptions.WebSocketException as e:
            # Handle other WebSocket exceptions (PRD-001 Section 1.4)
            self._set_connection_state(ConnectionState.DISCONNECTED, f"WebSocket error: {str(e)}")
            self.logger.error(f"Kraken WS protocol error: {e}")
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                KRAKEN_WS_ERRORS_TOTAL.labels(error_type='websocket_protocol').inc()
            raise
        except Exception as e:
            # Set state to DISCONNECTED on error (PRD-001 Section 4.1)
            self._set_connection_state(ConnectionState.DISCONNECTED, f"Connection error: {str(e)}")
            self.logger.error(f"Kraken WS connection error: {e}")  # PRD-001 Section 1.4: ERROR level with exception details
            # Emit Prometheus counter (PRD-001 Section 1.4)
            if PROMETHEUS_AVAILABLE and KRAKEN_WS_ERRORS_TOTAL:
                KRAKEN_WS_ERRORS_TOTAL.labels(error_type='connection').inc()
            raise

    async def start(self):
        """Start the WebSocket client with enhanced reconnection logic (PRD-001 Section 4.2)"""
        self.running = True
        await self.redis_manager.initialize_pool()

        backoff = self.config.reconnect_delay
        max_backoff = 60

        while self.running:
            try:
                await self.circuit_breakers["connection"].call(self.connect_once)
                # If we get here, connection closed normally
                if not self.running:
                    break

                # Reset backoff and reconnection attempt on successful connection (PRD-001 Section 4.2)
                backoff = self.config.reconnect_delay
                self.reconnection_attempt = 0
                self.logger.info("Connection successful - reconnection attempt counter reset to 0")

            except Exception as e:
                self.reconnection_attempt += 1
                self.stats["reconnects"] += 1  # Keep historical total

                # Emit Prometheus counter for reconnection attempts (PRD-001 Section 4.2)
                if PROMETHEUS_AVAILABLE and KRAKEN_WS_RECONNECTS_TOTAL:
                    KRAKEN_WS_RECONNECTS_TOTAL.inc()

                # Set state to RECONNECTING (PRD-001 Section 4.1)
                self._set_connection_state(
                    ConnectionState.RECONNECTING,
                    f"Reconnection attempt {self.reconnection_attempt}/{self.config.max_retries}"
                )

                self.logger.error(
                    f"Kraken WS connection failed (attempt {self.reconnection_attempt}/{self.config.max_retries}): {e}"
                )

                if self.reconnection_attempt >= self.config.max_retries:
                    self.logger.error("Kraken WS max reconnection attempts reached")
                    # Set state to DISCONNECTED after max retries
                    self._set_connection_state(ConnectionState.DISCONNECTED, "Max reconnection attempts reached")

                    # Trigger critical alert (PRD-001 Section 4.2)
                    if DISCORD_ALERTS_AVAILABLE and send_alert:
                        try:
                            send_alert(
                                title="⚠️ Kraken WebSocket: Max Reconnection Attempts Reached",
                                description=(
                                    f"Bot has failed to reconnect after {self.config.max_retries} attempts. "
                                    f"WebSocket connection to {self.config.url} is down. "
                                    f"Bot is now marked as UNHEALTHY and requires intervention."
                                ),
                                severity="CRITICAL",
                                tags={
                                    "component": "kraken_ws",
                                    "max_retries": str(self.config.max_retries),
                                    "pairs": ", ".join(self.config.pairs)
                                }
                            )
                            self.logger.info("Critical alert sent for max reconnection attempts")
                        except Exception as alert_error:
                            self.logger.error(f"Failed to send critical alert: {alert_error}")

                    break

                # Calculate backoff with ±20% jitter (PRD-001 Section 4.2)
                jitter = random.uniform(-0.2, 0.2)
                jitter_pct = jitter * 100
                backoff_with_jitter = backoff * (1 + jitter)

                # Log reconnection attempt with attempt number and wait time (PRD-001 Section 4.2 & 8.1)
                self.logger.info(
                    f"Reconnection attempt {self.reconnection_attempt}/{self.config.max_retries}: "
                    f"waiting {backoff_with_jitter:.1f}s before retry "
                    f"(base: {backoff}s, jitter: {jitter_pct:+.0f}%)"
                )

                await asyncio.sleep(backoff_with_jitter)

                # Check if shutdown requested during sleep (PRD-001 Section 4.2)
                if not self.running:
                    self.logger.info("Reconnection cancelled - graceful shutdown in progress")
                    break

                # Exponential backoff: double each time (PRD-001 Section 4.2)
                backoff = min(backoff * 2, max_backoff)

    async def stop(self):
        """Stop the WebSocket client (PRD-001 Section 9.1)"""
        self.logger.info("Stopping Kraken WebSocket client...")
        self.running = False

        # Set state to DISCONNECTED (PRD-001 Section 4.1)
        self._set_connection_state(ConnectionState.DISCONNECTED, "Graceful shutdown requested")

        if self.ws:
            await self.ws.close()

        await self.redis_manager.close()

        self.logger.info("Kraken WebSocket client stopped")

    def get_stats(self) -> dict:
        """Get comprehensive connection statistics (PRD-001 Section 8.2)"""
        latency_stats = self.latency_tracker.get_stats() if self.latency_tracker else {}
        cb_statuses = {name: cb.state.value for name, cb in self.circuit_breakers.items()}

        return {
            **self.stats,
            "running": self.running,
            "connection_state": self.connection_state.value,  # PRD-001 Section 4.1
            "is_healthy": self.is_healthy,  # PRD-001 Section 4.1 - Health based on connection duration
            "reconnection_attempt": self.reconnection_attempt,  # PRD-001 Section 4.2 - Current reconnection attempt
            "redis_connected": self.redis_manager.redis_client is not None,
            "latency_stats": latency_stats,
            "circuit_breakers": cb_statuses,
            "config": self.config.model_dump()
        }


# Production callbacks and integrations - Redis Cloud optimized
async def production_scalping_callback(pair: str, trades: List[dict]):
    """Production scalping strategy callback - Redis Cloud optimized"""
    for trade in trades:
        # Log significant trades for scalping analysis
        if trade["volume"] >= float(os.getenv("SCALP_MIN_VOLUME", "0.1")):
            target_bps = int(os.getenv("SCALP_TARGET_BPS", "10"))
            
            print(
                f"🎯 SCALP SIGNAL {pair}: {trade['side'].upper()} "
                f"{trade['volume']:.4f} @ ${trade['price']:.2f}"
            )
            print(f"   Target: {target_bps} bps, Volume: {trade['volume']:.4f}")
            
            # This is where you'd integrate with your MCP brain
            # signal_data = {
            #     "strategy": "scalp",
            #     "pair": pair,
            #     "signal": "entry",
            #     "price": trade["price"],
            #     "volume": trade["volume"],
            #     "target_bps": target_bps
            # }


async def production_spread_callback(pair: str, spread_data: dict):
    """Production spread monitoring callback - Redis Cloud optimized"""
    spread_bps = spread_data["spread_bps"]
    max_spread = float(os.getenv("SPREAD_BPS_MAX", "5.0"))
    
    if spread_bps <= 2.0:  # Very tight spread
        print(f"💎 TIGHT SPREAD {pair}: {spread_bps:.2f} bps - excellent for scalping!")
    elif spread_bps > max_spread:
        print(f"⚠️ WIDE SPREAD {pair}: {spread_bps:.2f} bps > {max_spread} bps limit")


async def production_circuit_breaker_callback(breaker_name: str, reason: str):
    """Production circuit breaker callback - Redis Cloud optimized"""
    print(f"🚨 CIRCUIT BREAKER ALERT: {breaker_name}")
    print(f"   Reason: {reason}")
    print(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
    
    # This is where you'd send alerts to Slack/Discord/monitoring systems
    alert_data = {
        "timestamp": datetime.now().isoformat(),
        "breaker": breaker_name,
        "reason": reason,
        "severity": "CRITICAL"
    }
    
    # Example integration points:
    # await send_slack_alert(alert_data)
    # await update_monitoring_dashboard(alert_data)
    # await pause_trading_strategies(breaker_name)


async def redis_cloud_monitoring_callback(breaker_name: str, reason: str):
    """Redis Cloud specific monitoring callback"""
    if "redis" in breaker_name.lower() or "memory" in reason.lower():
        print(f"🔧 REDIS CLOUD ALERT: {breaker_name}")
        print(f"   Reason: {reason}")
        print(f"   Time: {datetime.now().strftime('%H:%M:%S')}")
        
        # Log Redis Cloud specific metrics
        try:
            print("   💾 Check Redis Cloud dashboard for memory usage")
            print("   🔌 Check connection pool status")
        except Exception as e:
            print(f"   ⚠️ Failed to get Redis Cloud metrics: {e}")


# Production deployment function - Redis Cloud optimized
async def production_main():
    """Production deployment with Redis Cloud optimizations"""
    
    # Setup logging
    logging.basicConfig(
        level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    logger = logging.getLogger(__name__)
    logger.info("🚀 Starting Production Kraken WebSocket with Redis Cloud...")
    
    # Validate environment with Redis Cloud specifics
    required_env_vars = ["REDIS_URL", "TRADING_PAIRS"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"❌ Missing required environment variables: {missing_vars}")
        return
    
    # Redis Cloud specific validation
    redis_url = os.getenv("REDIS_URL", "")
    if "redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com" not in redis_url:
        logger.warning("⚠️ Not using verified Redis Cloud instance")
    
    # Create production configuration
    try:
        config = KrakenWSConfig()
        logger.info("✅ Redis Cloud optimized configuration loaded:")
        logger.info(f"   Pairs: {config.pairs}")
        logger.info(f"   Timeframes: {config.timeframes}")
        logger.info(f"   Redis: {'✅ Redis Cloud' if config.redis_url else '❌ Not configured'}")
        logger.info(f"   Scalping: {'✅ Enabled' if config.scalp_enabled else '❌ Disabled'}")
        logger.info("   Circuit Breakers: ✅ Redis Cloud Optimized")
        logger.info(f"   Pool Size: {config.redis_pool_size} (optimized for Redis Cloud)")
        logger.info(f"   Socket Timeout: {config.redis_socket_timeout}s (optimized)")
        logger.info(f"   Batch Size: {config.redis_batch_size} (optimized)")
        
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        return
    
    # Create client with Redis Cloud optimizations
    client = KrakenWebSocketClient(config)
    
    # Register production callbacks with Redis Cloud awareness
    client.register_callback("trade", production_scalping_callback)
    client.register_callback("spread", production_spread_callback)
    client.register_callback("circuit_breaker", production_circuit_breaker_callback)
    client.register_callback("circuit_breaker", redis_cloud_monitoring_callback)
    
    try:
        logger.info("🎯 Starting production WebSocket with Redis Cloud streams...")
        await client.start()
        
    except KeyboardInterrupt:
        logger.info("\n⏹️ Graceful shutdown initiated...")
    except Exception as e:
        logger.error(f"❌ Production error: {e}")
    finally:
        await client.stop()
        logger.info("✅ Production shutdown complete")


# Test function for development - Redis Cloud optimized
async def test_redis_connection():
    """Test Redis connection separately - Redis Cloud optimized"""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("❌ REDIS_URL not set in environment")
        return False
    
    try:
        # Use environment variable for security - NO hardcoded credentials
        client = redis.from_url(
            redis_url,
            ssl_cert_reqs='required' if redis_url.startswith('rediss://') else None,
            decode_responses=False,
            socket_timeout=10,  # Redis Cloud optimized
            socket_keepalive=True,
            socket_connect_timeout=5  # Redis Cloud optimized
        )
        
        # Test basic connection
        await client.ping()
        print("✅ Redis Cloud connection successful!")
        
        # Test stream operations
        test_data = {"test": "connection", "timestamp": str(time.time())}
        await client.xadd("test:stream", test_data, maxlen=100)
        print("✅ Redis Cloud stream write successful!")
        
        # Test memory info (Redis Cloud specific)
        try:
            info = await client.info('memory')
            memory_mb = int(info.get('used_memory', 0)) / (1024 * 1024)
            print(f"✅ Redis Cloud memory usage: {memory_mb:.1f}MB")
        except Exception as e:
            print(f"⚠️ Could not get memory info: {e}")
        
        # Clean up test data
        await client.delete("test:stream")
        await client.aclose()
        print("✅ Redis Cloud test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Redis Cloud connection failed: {e}")
        return False


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test-redis":
        # Test Redis connection only
        asyncio.run(test_redis_connection())
    else:
        # Run production WebSocket
        asyncio.run(production_main())