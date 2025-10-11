"""
Centralized logging key constants for structured logging.

This module provides standardized key names for use in logging dictionaries,
error details, and structured log entries. Using constants instead of magic
strings improves maintainability, enables IDE autocomplete, and prevents typos.

Usage:
    from agents.core.log_keys import K_COMPONENT, K_PAIR, K_STRATEGY

    logger.info("Trade executed", extra={
        K_COMPONENT: "execution_agent",
        K_PAIR: "BTC/USD",
        K_STRATEGY: "scalp"
    })
"""

from __future__ import annotations

# ==============================================================================
# Trading-specific keys
# ==============================================================================

# Trading symbols and instruments
K_SYMBOL = "symbol"
K_PAIR = "pair"
K_EXCHANGE = "exchange"

# Order and trade information
K_ORDER_ID = "order_id"
K_TRADE_ID = "trade_id"
K_SIGNAL_ID = "signal_id"
K_SIDE = "side"
K_QUANTITY = "quantity"
K_SIZE = "size"
K_PRICE = "price"
K_FILLED_QUANTITY = "filled_quantity"
K_AVERAGE_FILL_PRICE = "average_fill_price"
K_FEE = "fee"
K_ORDER_TYPE = "order_type"
K_STATUS = "status"
K_TIME_IN_FORCE = "time_in_force"

# Signal and strategy information
K_STRATEGY = "strategy"
K_SIGNAL_TYPE = "signal_type"
K_CONFIDENCE = "confidence"
K_QUALITY = "quality"
K_URGENCY = "urgency"
K_UNIFIED_SIGNAL = "unified_signal"
K_REGIME = "regime"
K_REGIME_STATE = "regime_state"
K_TARGET_STRATEGY = "target_strategy"

# Risk parameters
K_STOP_LOSS = "stop_loss"
K_STOP_LOSS_BPS = "stop_loss_bps"
K_TAKE_PROFIT = "take_profit"
K_TAKE_PROFIT_BPS = "take_profit_bps"
K_MAX_SLIPPAGE_BPS = "max_slippage_bps"
K_SLIPPAGE_BPS = "slippage_bps"
K_RISK_SCORE = "risk_score"
K_POSITION_SIZE_PCT = "position_size_pct"

# Timeframes and timing
K_TIMEFRAME = "timeframe"
K_TIMESTAMP = "timestamp"
K_TIMESTAMP_MS = "timestamp_ms"
K_TTL_SECONDS = "ttl_seconds"
K_TTL_MS = "ttl_ms"
K_UPDATED_AT = "updated_at"
K_CREATED_AT = "created_at"

# Market data
K_BID = "bid"
K_ASK = "ask"
K_LAST_PRICE = "last_price"
K_SPREAD_BPS = "spread_bps"
K_MID_PRICE = "mid_price"
K_VOLUME = "volume"
K_QUOTE_VOLUME = "quote_volume"
K_NOTIONAL = "notional"

# ==============================================================================
# System and component keys
# ==============================================================================

# Component identification
K_COMPONENT = "component"
K_MODULE = "module"
K_FUNCTION = "function"
K_CLASS = "class"
K_AGENT = "agent"
K_SERVICE = "service"

# Session and correlation
K_SESSION_ID = "session_id"
K_REQUEST_ID = "request_id"
K_CORRELATION_ID = "correlation_id"
K_TRACE_ID = "trace_id"

# Error and debugging
K_ERROR = "error"
K_ERROR_TYPE = "error_type"
K_ERROR_CODE = "error_code"
K_ERROR_MESSAGE = "error_message"
K_EXCEPTION = "exception"
K_ORIGINAL_ERROR = "original_error"
K_TRACEBACK = "traceback"

# ==============================================================================
# Performance and metrics keys
# ==============================================================================

# Latency metrics
K_LATENCY_MS = "latency_ms"
K_DURATION_MS = "duration_ms"
K_EXECUTION_TIME_MS = "execution_time_ms"
K_LAT_P50 = "lat_p50"
K_LAT_P95 = "lat_p95"
K_LAT_P99 = "lat_p99"

# Performance metrics
K_AVG_TIME_MS = "avg_time_ms"
K_MIN_TIME_MS = "min_time_ms"
K_MAX_TIME_MS = "max_time_ms"
K_COUNT = "count"
K_TOTAL_TIME = "total_time"

# Operation tracking
K_OPERATION = "operation"
K_ACTION = "action"
K_EVENT_TYPE = "event_type"
K_OPERATION_STATUS = "operation_status"

# ==============================================================================
# Configuration and validation keys
# ==============================================================================

# Configuration
K_CONFIG = "config"
K_CONFIG_KEY = "config_key"
K_CONFIG_FILE = "config_file"
K_CONFIG_PATH = "config_path"
K_VERSION = "version"

# Validation
K_FIELD_NAME = "field_name"
K_FIELD_VALUE = "field_value"
K_EXPECTED_TYPE = "expected_type"
K_EXPECTED_VALUE = "expected_value"
K_ACTUAL_VALUE = "actual_value"
K_VALID = "valid"

# ==============================================================================
# Network and connectivity keys
# ==============================================================================

# Redis and streams
K_STREAM = "stream"
K_STREAM_NAME = "stream_name"
K_CONSUMER_GROUP = "consumer_group"
K_CONSUMER_NAME = "consumer_name"
K_MESSAGE_ID = "message_id"

# API and networking
K_ENDPOINT = "endpoint"
K_URL = "url"
K_REDIS_URL = "redis_url"
K_API_METHOD = "api_method"
K_HTTP_STATUS = "http_status"
K_RETRY_COUNT = "retry_count"
K_TIMEOUT = "timeout"

# ==============================================================================
# Risk management keys
# ==============================================================================

# Risk limits and rules
K_RULE_NAME = "rule_name"
K_CURRENT_VALUE = "current_value"
K_LIMIT_VALUE = "limit_value"
K_LIMIT = "limit"
K_BREACH_AMOUNT = "breach_amount"
K_ACTION_TAKEN = "action_taken"

# Risk types
K_RISK_TYPE = "risk_type"
K_RISK_DATA = "risk_data"
K_RISK_OK = "risk_ok"

# Portfolio metrics
K_REQUIRED_BALANCE = "required_balance"
K_AVAILABLE_BALANCE = "available_balance"
K_CURRENCY = "currency"
K_CURRENT_DRAWDOWN = "current_drawdown"
K_MAX_DRAWDOWN = "max_drawdown"

# ==============================================================================
# Logging and audit keys
# ==============================================================================

# Log categories
K_CATEGORY = "category"
K_LOG_LEVEL = "log_level"
K_SEVERITY = "severity"

# Audit trail
K_TRADE_DATA = "trade_data"
K_SYSTEM_DATA = "system_data"
K_AUDIT_TRAIL = "audit_trail"

# ==============================================================================
# Data and processing keys
# ==============================================================================

# Data types and sources
K_DATA_TYPE = "data_type"
K_DATA_SOURCE = "source"
K_DATA_AGE_SECONDS = "data_age_seconds"
K_MAX_AGE_SECONDS = "max_age_seconds"

# Processing metadata
K_PRIORITY = "priority"
K_FEATURES = "features"
K_NOTES = "notes"
K_METADATA = "metadata"
K_CONTEXT = "context"

# Counts and limits
K_REQUIRED_BARS = "required_bars"
K_ACTUAL_BARS = "actual_bars"
K_PAIRS_FOUND = "pairs_found"
K_MISSING_FIELDS = "missing_fields"

# ==============================================================================
# Technical analysis keys
# ==============================================================================

# Indicators
K_RSI = "rsi"
K_MACD = "macd"
K_MACD_SIGNAL = "macd_signal"
K_BB_WIDTH = "bb_width"
K_TREND_STRENGTH = "trend_strength"

# Analysis results
K_TA_ANALYSIS = "ta_analysis"
K_SENTIMENT_ANALYSIS = "sentiment_analysis"
K_MACRO_ANALYSIS = "macro_analysis"
K_MARKET_CONTEXT = "market_context"

# Sentiment
K_SENTIMENT_SCORE = "sentiment_score"
K_SENTIMENT_TREND = "sentiment_trend"
K_MACRO_SIGNAL = "macro_signal"
K_MACRO_NOTES = "macro_notes"

# ==============================================================================
# Scalper-specific keys (for agents/scalper/infra)
# ==============================================================================

# Scalping metrics
K_TARGET_BPS = "target_bps"
K_EFFECTIVE_SPREAD_BPS = "effective_spread_bps"
K_SIZE_QUOTE_USD = "size_quote_usd"
K_REBATE_EARNED = "rebate_earned"

# Execution details
K_REJECTION_REASON = "rejection_reason"
K_INSTALL_COMMAND = "install_command"
K_MISSING_PACKAGE = "missing_package"

# Intent and result
K_ORDER_INTENT = "order_intent"
K_EXECUTION_RESULT = "execution_result"
K_SUCCESS = "success"

# ==============================================================================
# Observability and metrics keys
# ==============================================================================

# Timing measurements
K_SIGNAL_ANALYSIS_MS = "signal_analysis_ms"
K_DECISION_TO_PUBLISH_MS = "decision_to_publish_ms"
K_GATEWAY_ROUNDTRIP_MS = "gateway_roundtrip_ms"
K_START_TIME = "start_time"
K_END_TIME = "end_time"
K_ELAPSED_MS = "elapsed_ms"

# Retry and resilience metrics
K_RETRY_ATTEMPT = "retry_attempt"
K_MAX_RETRIES = "max_retries"
K_RETRIES_EXHAUSTED = "retries_exhausted"
K_BACKOFF_MS = "backoff_ms"

# Throttling metrics
K_THROTTLED = "throttled"
K_THROTTLE_REASON = "throttle_reason"
K_THROTTLE_DURATION_MS = "throttle_duration_ms"
K_RATE_LIMIT_REMAINING = "rate_limit_remaining"
K_RATE_LIMIT_RESET = "rate_limit_reset"

# Circuit breaker metrics
K_CIRCUIT_BREAKER = "circuit_breaker"
K_CIRCUIT_STATE = "circuit_state"
K_CIRCUIT_BREAKER_TRIP = "circuit_breaker_trip"
K_FAILURE_COUNT = "failure_count"
K_FAILURE_THRESHOLD = "failure_threshold"
K_CIRCUIT_OPEN_UNTIL = "circuit_open_until"

# Counter metrics
K_COUNTER_NAME = "counter_name"
K_COUNTER_VALUE = "counter_value"
K_COUNTER_DELTA = "counter_delta"

# Gauge metrics
K_GAUGE_NAME = "gauge_name"
K_GAUGE_VALUE = "gauge_value"

# Histogram metrics
K_HISTOGRAM_NAME = "histogram_name"
K_HISTOGRAM_VALUE = "histogram_value"
K_BUCKET = "bucket"

# ==============================================================================
# Exports
# ==============================================================================

__all__ = [
    # Trading
    "K_SYMBOL",
    "K_PAIR",
    "K_EXCHANGE",
    "K_ORDER_ID",
    "K_TRADE_ID",
    "K_SIGNAL_ID",
    "K_SIDE",
    "K_QUANTITY",
    "K_SIZE",
    "K_PRICE",
    "K_FILLED_QUANTITY",
    "K_AVERAGE_FILL_PRICE",
    "K_FEE",
    "K_ORDER_TYPE",
    "K_STATUS",
    "K_TIME_IN_FORCE",
    # Signals
    "K_STRATEGY",
    "K_SIGNAL_TYPE",
    "K_CONFIDENCE",
    "K_QUALITY",
    "K_URGENCY",
    "K_UNIFIED_SIGNAL",
    "K_REGIME",
    "K_REGIME_STATE",
    "K_TARGET_STRATEGY",
    # Risk
    "K_STOP_LOSS",
    "K_STOP_LOSS_BPS",
    "K_TAKE_PROFIT",
    "K_TAKE_PROFIT_BPS",
    "K_MAX_SLIPPAGE_BPS",
    "K_SLIPPAGE_BPS",
    "K_RISK_SCORE",
    "K_POSITION_SIZE_PCT",
    # Timing
    "K_TIMEFRAME",
    "K_TIMESTAMP",
    "K_TIMESTAMP_MS",
    "K_TTL_SECONDS",
    "K_TTL_MS",
    "K_UPDATED_AT",
    "K_CREATED_AT",
    # Market data
    "K_BID",
    "K_ASK",
    "K_LAST_PRICE",
    "K_SPREAD_BPS",
    "K_MID_PRICE",
    "K_VOLUME",
    "K_QUOTE_VOLUME",
    "K_NOTIONAL",
    # System
    "K_COMPONENT",
    "K_MODULE",
    "K_FUNCTION",
    "K_CLASS",
    "K_AGENT",
    "K_SERVICE",
    "K_SESSION_ID",
    "K_REQUEST_ID",
    "K_CORRELATION_ID",
    "K_TRACE_ID",
    # Errors
    "K_ERROR",
    "K_ERROR_TYPE",
    "K_ERROR_CODE",
    "K_ERROR_MESSAGE",
    "K_EXCEPTION",
    "K_ORIGINAL_ERROR",
    "K_TRACEBACK",
    # Performance
    "K_LATENCY_MS",
    "K_DURATION_MS",
    "K_EXECUTION_TIME_MS",
    "K_LAT_P50",
    "K_LAT_P95",
    "K_LAT_P99",
    "K_AVG_TIME_MS",
    "K_MIN_TIME_MS",
    "K_MAX_TIME_MS",
    "K_COUNT",
    "K_TOTAL_TIME",
    "K_OPERATION",
    "K_ACTION",
    "K_EVENT_TYPE",
    "K_OPERATION_STATUS",
    # Configuration
    "K_CONFIG",
    "K_CONFIG_KEY",
    "K_CONFIG_FILE",
    "K_CONFIG_PATH",
    "K_VERSION",
    "K_FIELD_NAME",
    "K_FIELD_VALUE",
    "K_EXPECTED_TYPE",
    "K_EXPECTED_VALUE",
    "K_ACTUAL_VALUE",
    "K_VALID",
    # Network
    "K_STREAM",
    "K_STREAM_NAME",
    "K_CONSUMER_GROUP",
    "K_CONSUMER_NAME",
    "K_MESSAGE_ID",
    "K_ENDPOINT",
    "K_URL",
    "K_REDIS_URL",
    "K_API_METHOD",
    "K_HTTP_STATUS",
    "K_RETRY_COUNT",
    "K_TIMEOUT",
    # Risk management
    "K_RULE_NAME",
    "K_CURRENT_VALUE",
    "K_LIMIT_VALUE",
    "K_LIMIT",
    "K_BREACH_AMOUNT",
    "K_ACTION_TAKEN",
    "K_RISK_TYPE",
    "K_RISK_DATA",
    "K_RISK_OK",
    "K_REQUIRED_BALANCE",
    "K_AVAILABLE_BALANCE",
    "K_CURRENCY",
    "K_CURRENT_DRAWDOWN",
    "K_MAX_DRAWDOWN",
    # Logging
    "K_CATEGORY",
    "K_LOG_LEVEL",
    "K_SEVERITY",
    "K_TRADE_DATA",
    "K_SYSTEM_DATA",
    "K_AUDIT_TRAIL",
    # Data
    "K_DATA_TYPE",
    "K_DATA_SOURCE",
    "K_DATA_AGE_SECONDS",
    "K_MAX_AGE_SECONDS",
    "K_PRIORITY",
    "K_FEATURES",
    "K_NOTES",
    "K_METADATA",
    "K_CONTEXT",
    "K_REQUIRED_BARS",
    "K_ACTUAL_BARS",
    "K_PAIRS_FOUND",
    "K_MISSING_FIELDS",
    # Technical analysis
    "K_RSI",
    "K_MACD",
    "K_MACD_SIGNAL",
    "K_BB_WIDTH",
    "K_TREND_STRENGTH",
    "K_TA_ANALYSIS",
    "K_SENTIMENT_ANALYSIS",
    "K_MACRO_ANALYSIS",
    "K_MARKET_CONTEXT",
    "K_SENTIMENT_SCORE",
    "K_SENTIMENT_TREND",
    "K_MACRO_SIGNAL",
    "K_MACRO_NOTES",
    # Scalper-specific
    "K_TARGET_BPS",
    "K_EFFECTIVE_SPREAD_BPS",
    "K_SIZE_QUOTE_USD",
    "K_REBATE_EARNED",
    "K_REJECTION_REASON",
    "K_INSTALL_COMMAND",
    "K_MISSING_PACKAGE",
    "K_ORDER_INTENT",
    "K_EXECUTION_RESULT",
    "K_SUCCESS",
    # Observability and metrics
    "K_SIGNAL_ANALYSIS_MS",
    "K_DECISION_TO_PUBLISH_MS",
    "K_GATEWAY_ROUNDTRIP_MS",
    "K_START_TIME",
    "K_END_TIME",
    "K_ELAPSED_MS",
    "K_RETRY_ATTEMPT",
    "K_MAX_RETRIES",
    "K_RETRIES_EXHAUSTED",
    "K_BACKOFF_MS",
    "K_THROTTLED",
    "K_THROTTLE_REASON",
    "K_THROTTLE_DURATION_MS",
    "K_RATE_LIMIT_REMAINING",
    "K_RATE_LIMIT_RESET",
    "K_CIRCUIT_BREAKER",
    "K_CIRCUIT_STATE",
    "K_CIRCUIT_BREAKER_TRIP",
    "K_FAILURE_COUNT",
    "K_FAILURE_THRESHOLD",
    "K_CIRCUIT_OPEN_UNTIL",
    "K_COUNTER_NAME",
    "K_COUNTER_VALUE",
    "K_COUNTER_DELTA",
    "K_GAUGE_NAME",
    "K_GAUGE_VALUE",
    "K_HISTOGRAM_NAME",
    "K_HISTOGRAM_VALUE",
    "K_BUCKET",
]
