"""
Central logger factory for crypto_ai_bot.

This module provides a centralized logging configuration that ensures:
- One-time global configuration
- No duplicate handlers on repeated imports
- Thread/async safe operation
- Redaction of sensitive information
- Consistent formatting across the application

Environment Variables:
    LOG_LEVEL: Logging level (default: INFO)
    LOG_TO_FILE: Whether to write to files (default: true)

Example Usage:
    ```python
    from utils.logger import get_logger, get_metrics_logger
    
    # Get a logger for a module
    logger = get_logger(__name__)
    logger.info("This is an info message")
    logger.debug("This debug message will only show if LOG_LEVEL=DEBUG")
    
    # Get a metrics logger
    metrics_logger = get_metrics_logger()
    metrics_logger.info("Trade executed: BTC/USD 100.0")
    
    # Logging with sensitive data (automatically redacted)
    logger.info("API key: sk-1234567890abcdef")  # Will be redacted
    ```
"""

import json
import logging
import os
import re
import sys
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class SecretRedactionFilter(logging.Filter):
    """Filter to redact sensitive information from log messages."""
    
    # Patterns that look like secrets, keys, tokens, passwords
    SECRET_PATTERNS = [
        r'(?i)(api[_-]?key|secret[_-]?key|access[_-]?token|refresh[_-]?token|password|passwd|pwd)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{8,})["\']?',
        r'(?i)(key|token|secret|password)\s*[:=]\s*["\']?([a-zA-Z0-9_\-\.]{8,})["\']?',
        r'(?i)(sk-|pk-|rk-|ak-|tk-)([a-zA-Z0-9]{20,})',
        r'(?i)(bearer\s+)([a-zA-Z0-9_\-\.]{20,})',
        r'(?i)(basic\s+)([a-zA-Z0-9+/=]{20,})',
        r'([a-f0-9]{32,})',  # Hex strings (like MD5, SHA hashes)
        r'([A-Za-z0-9+/]{40,}={0,2})',  # Base64-like strings
    ]
    
    def __init__(self):
        super().__init__()
        self._compiled_patterns = [re.compile(pattern) for pattern in self.SECRET_PATTERNS]
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter and redact sensitive information from the log record."""
        if hasattr(record, 'getMessage'):
            message = record.getMessage()
            redacted_message = self._redact_message(message)
            if redacted_message != message:
                # Update the record with redacted message
                record.msg = redacted_message
                record.args = ()
        return True
    
    def _redact_message(self, message: str) -> str:
        """Redact sensitive information from a message."""
        redacted = message
        for pattern in self._compiled_patterns:
            redacted = pattern.sub(r'\1[REDACTED]', redacted)
        return redacted


class LoggerFactory:
    """Thread-safe logger factory with global configuration."""
    
    _instance = None
    _lock = threading.Lock()
    _configured = False
    
    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        if not self._configured:
            with self._lock:
                if not self._configured:
                    self._setup_logging()
                    self._configured = True
    
    def _setup_logging(self):
        """Set up global logging configuration."""
        # Get configuration from environment
        log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        log_to_file = os.getenv('LOG_TO_FILE', 'true').lower() in ('true', '1', 'yes', 'on')
        log_format = os.getenv('LOG_FORMAT', '').lower()
        use_json = log_format == 'json'
        
        # Create logs directory if it doesn't exist
        logs_dir = Path('logs')
        logs_dir.mkdir(exist_ok=True)
        
        # Set up formatter (JSON or text)
        if use_json:
            formatter = self._create_json_formatter()
        else:
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(name)s | %(message)s',
                datefmt='%Y-%m-%dT%H:%M:%S'
            )
        
        # Create redaction filter
        redaction_filter = SecretRedactionFilter()
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        # Clear any existing handlers to prevent duplicates
        root_logger.handlers.clear()
        
        # Always add console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level, logging.INFO))
        console_handler.setFormatter(formatter)
        console_handler.addFilter(redaction_filter)
        root_logger.addHandler(console_handler)
        
        # Ensure handlers flush immediately
        console_handler.flush()
        
        # Add file handler if enabled
        if log_to_file:
            # Main application log file
            main_file_handler = logging.FileHandler(
                logs_dir / 'crypto_ai_bot.log',
                mode='a',
                encoding='utf-8'
            )
            main_file_handler.setLevel(getattr(logging, log_level, logging.INFO))
            main_file_handler.setFormatter(formatter)
            main_file_handler.addFilter(redaction_filter)
            root_logger.addHandler(main_file_handler)
            
            # Ensure file handler flushes immediately
            main_file_handler.flush()
            
            # Metrics log file
            metrics_file_handler = logging.FileHandler(
                logs_dir / 'metrics.log',
                mode='a',
                encoding='utf-8'
            )
            metrics_file_handler.setLevel(logging.INFO)  # Metrics always at INFO level
            metrics_file_handler.setFormatter(formatter)
            metrics_file_handler.addFilter(redaction_filter)
            root_logger.addHandler(metrics_file_handler)
            
            # Ensure metrics file handler flushes immediately
            metrics_file_handler.flush()
    
    def _create_json_formatter(self) -> logging.Formatter:
        """Create a JSON formatter for structured logging (PRD-001 Section 9.4)."""
        class JSONFormatter(logging.Formatter):
            """Structured JSON formatter for investor-ready logs."""
            
            def format(self, record: logging.LogRecord) -> str:
                """Format log record as JSON."""
                log_entry: Dict[str, Any] = {
                    "timestamp": datetime.fromtimestamp(
                        record.created, tz=timezone.utc
                    ).isoformat(),
                    "level": record.levelname,
                    "component": record.name,
                    "message": record.getMessage(),
                }
                
                # Add context fields if present
                if hasattr(record, 'pair'):
                    log_entry['pair'] = record.pair
                if hasattr(record, 'signal_id'):
                    log_entry['signal_id'] = record.signal_id
                if hasattr(record, 'strategy'):
                    log_entry['strategy'] = record.strategy
                if hasattr(record, 'context'):
                    log_entry['context'] = record.context
                
                # Add exception info if present
                if record.exc_info:
                    try:
                        etype = record.exc_info[0].__name__ if record.exc_info[0] else None
                        emsg = str(record.exc_info[1]) if record.exc_info[1] else None
                        etb = traceback.format_exception(*record.exc_info)
                        log_entry['exception'] = {
                            "type": etype,
                            "message": emsg,
                            "traceback": etb
                        }
                    except Exception:
                        pass
                
                # Add any extra fields
                for key, value in record.__dict__.items():
                    if key not in {
                        'name', 'msg', 'args', 'levelname', 'levelno', 'pathname',
                        'filename', 'module', 'exc_info', 'exc_text', 'stack_info',
                        'lineno', 'funcName', 'created', 'msecs', 'relativeCreated',
                        'thread', 'threadName', 'processName', 'process', 'getMessage'
                    }:
                        if key not in log_entry:
                            log_entry[key] = value
                
                return json.dumps(log_entry, default=str)
        
        return JSONFormatter()
    
    def get_logger(self, name: str, level: Optional[str] = None) -> logging.Logger:
        """Get a logger instance with the specified name and optional level override.
        
        Args:
            name: Logger name (typically __name__)
            level: Optional level override (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            
        Returns:
            Configured logger instance
        """
        logger = logging.getLogger(name)
        
        if level:
            logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        
        return logger
    
    def get_metrics_logger(self) -> logging.Logger:
        """Get a logger specifically for metrics that writes to logs/metrics.log.
        
        Returns:
            Logger configured for metrics logging
        """
        return logging.getLogger('metrics')


# Global factory instance (lazy initialization)
_factory: Optional[LoggerFactory] = None


def _get_factory() -> LoggerFactory:
    """Get or create the global logger factory (lazy initialization)."""
    global _factory
    if _factory is None:
        _factory = LoggerFactory()
    return _factory


def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """Get a logger instance with the specified name and optional level override.
    
    This function provides a convenient way to get loggers throughout the application.
    The logger will inherit the global configuration and will not create duplicate handlers.
    
    Args:
        name: Logger name (typically __name__)
        level: Optional level override (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        
    Returns:
        Configured logger instance
        
    Example:
        ```python
        from utils.logger import get_logger
        
        logger = get_logger(__name__)
        logger.info("Application started")
        
        # With level override
        debug_logger = get_logger(__name__, "DEBUG")
        debug_logger.debug("Detailed debug information")
        ```
    """
    return _get_factory().get_logger(name, level)


def get_metrics_logger() -> logging.Logger:
    """Get a logger specifically for metrics that writes to logs/metrics.log.
    
    This logger is optimized for metrics and trading data logging.
    It will write to both console and the dedicated metrics.log file.
    
    Returns:
        Logger configured for metrics logging
        
    Example:
        ```python
        from utils.logger import get_metrics_logger
        
        metrics_logger = get_metrics_logger()
        metrics_logger.info("Trade executed: BTC/USD 100.0 @ 50000.0")
        metrics_logger.info("Portfolio value: $100000.0")
        ```
    """
    return _get_factory().get_metrics_logger()


# Convenience function for backward compatibility
def setup_logging():
    """Set up logging configuration. Called automatically on import."""
    pass  # Configuration is done automatically in LoggerFactory.__init__


if __name__ == "__main__":
    # Test the logger
    logger = get_logger(__name__)
    metrics_logger = get_metrics_logger()
    
    logger.info("Logger factory test started")
    logger.debug("This is a debug message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    
    # Test redaction
    logger.info("API key: sk-1234567890abcdef")
    logger.info("Password: mysecretpassword123")
    logger.info("Token: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
    
    # Test metrics logger
    metrics_logger.info("Test metric: value=42.0")
    metrics_logger.info("Trade executed: BTC/USD 1.0 @ 50000.0")
    
    logger.info("Logger factory test completed")
