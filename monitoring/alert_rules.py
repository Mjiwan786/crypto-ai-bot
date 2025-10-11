"""
Alert Rules Engine

This module provides a minimal scheduler that evaluates predefined alert rules
and sends Discord alerts when thresholds are breached.

Rules:
1. No signals for N minutes - monitors signal publishing activity
2. Heartbeat missing - monitors Redis heartbeat key
3. Redis error rate spikes - monitors Redis publish error rates

Usage:
    from monitoring.alert_rules import run_alert_daemon
    await run_alert_daemon(redis_client, config)
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import json

logger = logging.getLogger(__name__)

# Environment configuration
ALERT_NO_SIGNALS_MIN = int(os.getenv("ALERT_NO_SIGNALS_MIN", "15"))
ALERT_REDIS_ERRORS_PER_MIN = int(os.getenv("ALERT_REDIS_ERRORS_PER_MIN", "10"))
ALERT_DEBOUNCE_MIN = int(os.getenv("ALERT_DEBOUNCE_MIN", "10"))  # Cooldown period in minutes

# Global state for debouncing and error tracking
_alert_cooldowns: Dict[str, float] = {}  # rule_key -> last_alert_time
_redis_error_counts: List[float] = []  # Sliding window of error counts
_last_metrics_check = 0.0
_last_daily_slo_alert = 0.0  # Track last daily SLO alert time


def _get_rule_key(rule_name: str, **kwargs) -> str:
    """Generate a unique key for alert debouncing."""
    key_parts = [rule_name]
    for k, v in sorted(kwargs.items()):
        key_parts.append(f"{k}={v}")
    return ":".join(key_parts)


def _is_alert_cooldown_active(rule_key: str) -> bool:
    """Check if an alert is in cooldown period."""
    if rule_key not in _alert_cooldowns:
        return False
    
    cooldown_seconds = ALERT_DEBOUNCE_MIN * 60
    return (time.time() - _alert_cooldowns[rule_key]) < cooldown_seconds


def _set_alert_cooldown(rule_key: str) -> None:
    """Set cooldown for an alert rule."""
    _alert_cooldowns[rule_key] = time.time()


def _send_alert_if_not_cooldown(rule_name: str, title: str, description: str, 
                               severity: str = "WARN", **kwargs) -> bool:
    """Send alert only if not in cooldown period."""
    rule_key = _get_rule_key(rule_name, **kwargs)
    
    if _is_alert_cooldown_active(rule_key):
        logger.debug(f"Alert {rule_name} in cooldown, skipping")
        return False
    
    try:
        from monitoring.discord_alerts import send_alert
        success = send_alert(title, description, severity, kwargs)
        if success:
            _set_alert_cooldown(rule_key)
            logger.info(f"Alert sent: {rule_name} - {title}")
        return success
    except ImportError:
        logger.warning(f"Discord alerts not available - would send: {title}")
        return False
    except Exception as e:
        logger.warning(f"Failed to send alert {rule_name}: {e}")
        return False


async def _check_no_signals_rule(redis_client, config: Dict[str, Any]) -> None:
    """
    Check if no signals have been published for the configured time period.
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    try:
        # Determine signal stream based on config mode
        mode = config.get("mode", "staging")
        if mode == "production":
            signal_stream = "signals:live"
        else:
            signal_stream = "signals:staging"
        
        # Get the last entry from the signal stream
        last_entry = None
        if hasattr(redis_client, 'xrevrange') and asyncio.iscoroutinefunction(redis_client.xrevrange):
            # Async Redis client
            entries = await redis_client.xrevrange(signal_stream, count=1)
        else:
            # Sync Redis client
            entries = redis_client.xrevrange(signal_stream, count=1)
        
        if entries:
            last_entry = entries[0]
        
        if not last_entry:
            # No entries in stream
            rule_key = _get_rule_key("no_signals", stream=signal_stream)
            if not _is_alert_cooldown_active(rule_key):
                _send_alert_if_not_cooldown(
                    "no_signals",
                    "No Signals Published",
                    f"No signals found in {signal_stream} stream",
                    "CRITICAL",
                    stream=signal_stream,
                    mode=mode
                )
            return
        
        # Parse timestamp from last entry
        entry_id, fields = last_entry
        timestamp_str = fields.get(b'timestamp', b'').decode('utf-8')
        
        try:
            # Try to parse as Unix timestamp
            if '.' in timestamp_str:
                last_ts = float(timestamp_str)
            else:
                last_ts = float(timestamp_str)
        except (ValueError, TypeError):
            # Try to parse as ISO timestamp
            try:
                from dateutil.parser import parse
                last_ts = parse(timestamp_str).timestamp()
            except:
                logger.warning(f"Could not parse timestamp: {timestamp_str}")
                return
        
        # Check if elapsed time exceeds threshold
        elapsed_minutes = (time.time() - last_ts) / 60
        
        if elapsed_minutes > ALERT_NO_SIGNALS_MIN:
            _send_alert_if_not_cooldown(
                "no_signals",
                "No Signals Published",
                f"No signals published for {elapsed_minutes:.1f} minutes (threshold: {ALERT_NO_SIGNALS_MIN} min)",
                "CRITICAL",
                stream=signal_stream,
                last_ts=timestamp_str,
                elapsed_minutes=f"{elapsed_minutes:.1f}",
                mode=mode
            )
        else:
            logger.debug(f"Signals OK - last published {elapsed_minutes:.1f} minutes ago")
            
    except Exception as e:
        logger.warning(f"Error checking no signals rule: {e}")


async def _check_heartbeat_rule(redis_client, config: Dict[str, Any]) -> None:
    """
    Check if the heartbeat key is missing or expired.
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    try:
        heartbeat_key = os.getenv("HEARTBEAT_KEY", "bot:heartbeat")
        
        # Check heartbeat key
        if hasattr(redis_client, 'get') and asyncio.iscoroutinefunction(redis_client.get):
            # Async Redis client
            heartbeat_value = await redis_client.get(heartbeat_key)
            ttl = await redis_client.ttl(heartbeat_key)
        else:
            # Sync Redis client
            heartbeat_value = redis_client.get(heartbeat_key)
            ttl = redis_client.ttl(heartbeat_key)
        
        if heartbeat_value is None:
            # Heartbeat key is missing
            _send_alert_if_not_cooldown(
                "heartbeat_missing",
                "Heartbeat Missing",
                f"Heartbeat key '{heartbeat_key}' is missing",
                "CRITICAL",
                key=heartbeat_key,
                status="missing"
            )
        elif ttl <= 0:
            # Heartbeat key is expired
            _send_alert_if_not_cooldown(
                "heartbeat_missing",
                "Heartbeat Expired",
                f"Heartbeat key '{heartbeat_key}' has expired (TTL: {ttl})",
                "CRITICAL",
                key=heartbeat_key,
                ttl=ttl,
                status="expired"
            )
        else:
            logger.debug(f"Heartbeat OK - TTL: {ttl}s, value: {heartbeat_value}")
            
    except Exception as e:
        logger.warning(f"Error checking heartbeat rule: {e}")


async def _check_redis_errors_rule(redis_client, config: Dict[str, Any]) -> None:
    """
    Check if Redis error rate has spiked.
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    global _redis_error_counts, _last_metrics_check
    
    try:
        current_time = time.time()
        
        # Try to get metrics from Prometheus endpoint
        try:
            import requests
            metrics_response = requests.get("http://localhost:9108/metrics", timeout=2)
            if metrics_response.status_code == 200:
                metrics_text = metrics_response.text
                
                # Parse redis_publish_errors_total from metrics
                error_count = 0
                for line in metrics_text.split('\n'):
                    if line.startswith('redis_publish_errors_total') and not line.startswith('#'):
                        # Extract the count value
                        parts = line.split()
                        if len(parts) >= 2:
                            try:
                                error_count = float(parts[1])
                                break
                            except ValueError:
                                continue
                
                # Add to sliding window
                _redis_error_counts.append((current_time, error_count))
                
                # Keep only last 2 minutes of data
                cutoff_time = current_time - 120
                _redis_error_counts = [(t, c) for t, c in _redis_error_counts if t > cutoff_time]
                
                if len(_redis_error_counts) >= 2:
                    # Calculate error rate per minute
                    time_span = _redis_error_counts[-1][0] - _redis_error_counts[0][0]
                    error_span = _redis_error_counts[-1][1] - _redis_error_counts[0][1]
                    
                    if time_span > 0:
                        errors_per_minute = (error_span / time_span) * 60
                        
                        if errors_per_minute > ALERT_REDIS_ERRORS_PER_MIN:
                            severity = "CRITICAL" if errors_per_minute > ALERT_REDIS_ERRORS_PER_MIN * 2 else "WARN"
                            
                            _send_alert_if_not_cooldown(
                                "redis_errors",
                                "Redis Error Rate Spike",
                                f"Redis publish errors: {errors_per_minute:.1f}/min (threshold: {ALERT_REDIS_ERRORS_PER_MIN}/min)",
                                severity,
                                errors_per_minute=f"{errors_per_minute:.1f}",
                                threshold=ALERT_REDIS_ERRORS_PER_MIN
                            )
                        else:
                            logger.debug(f"Redis errors OK - {errors_per_minute:.1f}/min")
                    else:
                        logger.debug("Not enough time span for Redis error rate calculation")
                else:
                    logger.debug("Not enough data points for Redis error rate calculation")
                    
        except ImportError:
            logger.debug("Requests not available for metrics scraping")
        except Exception as e:
            logger.debug(f"Could not scrape metrics: {e}")
            
    except Exception as e:
        logger.warning(f"Error checking Redis errors rule: {e}")


async def _check_daily_slo_summary(redis_client, config: Dict[str, Any]) -> None:
    """
    Check and send daily SLO window summary at 00:15 UTC.
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    global _last_daily_slo_alert
    
    try:
        current_time = time.time()
        current_utc = datetime.now(timezone.utc)
        
        # Check if it's time for daily SLO summary (00:15 UTC)
        should_check = (
            current_utc.hour == 0 and 
            current_utc.minute >= 15 and 
            current_utc.minute < 20  # 5-minute window
        )
        
        # Debounce to once per day
        if not should_check:
            return
            
        # Check if we already sent an alert today
        if current_time - _last_daily_slo_alert < 86400:  # 24 hours
            return
        
        # Get current SLO status from Redis
        slo_status = await _get_slo_status(redis_client)
        if not slo_status:
            logger.warning("Could not retrieve SLO status for daily summary")
            return
        
        # Send appropriate alert based on SLO status
        await _send_daily_slo_alert(slo_status, config)
        
        # Update last alert time
        _last_daily_slo_alert = current_time
        
    except Exception as e:
        logger.warning(f"Error checking daily SLO summary: {e}")


async def _get_slo_status(redis_client) -> Optional[Dict[str, Any]]:
    """
    Get current SLO status from Redis.
    
    Args:
        redis_client: Redis client
        
    Returns:
        SLO status dictionary or None if not available
    """
    try:
        if hasattr(redis_client, 'hgetall') and asyncio.iscoroutinefunction(redis_client.hgetall):
            status_data = await redis_client.hgetall("slo:status")
        else:
            status_data = redis_client.hgetall("slo:status")
        
        if not status_data:
            return None
        
        # Convert bytes to strings if needed
        result = {}
        for key, value in status_data.items():
            if isinstance(key, bytes):
                key = key.decode()
            if isinstance(value, bytes):
                value = value.decode()
            result[key] = value
        
        # Parse JSON fields
        if 'breaches' in result:
            result['breaches'] = json.loads(result['breaches'])
        if 'warnings' in result:
            result['warnings'] = json.loads(result['warnings'])
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to get SLO status: {e}")
        return None


async def _send_daily_slo_alert(slo_status: Dict[str, Any], config: Dict[str, Any]) -> None:
    """
    Send daily SLO summary alert based on status.
    
    Args:
        slo_status: SLO status dictionary
        config: Configuration dictionary
    """
    try:
        status = slo_status.get('status', 'UNKNOWN')
        window_hours = slo_status.get('window_hours', '72')
        
        # Format metrics for display
        p95_latency = float(slo_status.get('p95_latency_ms', 0))
        stream_lag_p95 = float(slo_status.get('stream_lag_p95_sec', 0))
        uptime_ratio = float(slo_status.get('uptime_ratio', 0))
        dup_rate = float(slo_status.get('dup_rate', 0))
        
        breaches = slo_status.get('breaches', [])
        warnings = slo_status.get('warnings', [])
        
        # Create tags for the alert
        tags = {
            "window_hours": window_hours,
            "p95_latency_ms": f"{p95_latency:.1f}",
            "stream_lag_p95_sec": f"{stream_lag_p95:.1f}",
            "uptime_ratio": f"{uptime_ratio:.3f}",
            "dup_rate": f"{dup_rate:.4f}",
            "breach_count": len(breaches),
            "warning_count": len(warnings)
        }
        
        if status == "FAIL":
            # CRITICAL alert for SLO failures
            title = "🚨 Daily SLO Summary - FAIL"
            description = f"**SLO Status: FAIL** - {len(breaches)} breach(es) detected\n\n"
            
            if breaches:
                description += "**Breached Metrics:**\n"
                for breach in breaches:
                    description += f"• {breach}\n"
                description += "\n"
            
            if warnings:
                description += "**Warnings:**\n"
                for warning in warnings:
                    description += f"• {warning}\n"
                description += "\n"
            
            description += "**Key Stats:**\n"
            description += f"• P95 Latency: {p95_latency:.1f}ms\n"
            description += f"• Stream Lag P95: {stream_lag_p95:.1f}s\n"
            description += f"• Uptime: {uptime_ratio:.1%}\n"
            description += f"• Dup Rate: {dup_rate:.2%}\n"
            description += f"• Window: {window_hours}h\n\n"
            description += "**Action Required:** Investigate and resolve SLO breaches immediately."
            
            _send_alert_if_not_cooldown(
                "daily_slo_summary",
                title,
                description,
                "CRITICAL",
                **tags
            )
            
        elif status == "WARN":
            # WARN alert for near-misses
            title = "⚠️ Daily SLO Summary - WARN"
            description = f"**SLO Status: WARN** - {len(warnings)} warning(s) detected\n\n"
            
            if warnings:
                description += "**Near-Miss Metrics:**\n"
                for warning in warnings:
                    description += f"• {warning}\n"
                description += "\n"
            
            description += "**Key Stats:**\n"
            description += f"• P95 Latency: {p95_latency:.1f}ms\n"
            description += f"• Stream Lag P95: {stream_lag_p95:.1f}s\n"
            description += f"• Uptime: {uptime_ratio:.1%}\n"
            description += f"• Dup Rate: {dup_rate:.2%}\n"
            description += f"• Window: {window_hours}h\n\n"
            description += "**Monitor:** Watch for potential SLO breaches."
            
            _send_alert_if_not_cooldown(
                "daily_slo_summary",
                title,
                description,
                "WARN",
                **tags
            )
            
        elif status == "PASS":
            # INFO alert for healthy status
            title = "✅ Daily SLO Summary - PASS"
            description = f"**SLO Status: PASS** - All metrics within thresholds\n\n"
            
            description += "**Key Stats:**\n"
            description += f"• P95 Latency: {p95_latency:.1f}ms ✅\n"
            description += f"• Stream Lag P95: {stream_lag_p95:.1f}s ✅\n"
            description += f"• Uptime: {uptime_ratio:.1%} ✅\n"
            description += f"• Dup Rate: {dup_rate:.2%} ✅\n"
            description += f"• Window: {window_hours}h\n\n"
            description += "**Status:** System operating within SLO targets."
            
            _send_alert_if_not_cooldown(
                "daily_slo_summary",
                title,
                description,
                "INFO",
                **tags
            )
            
        else:
            # Unknown status
            title = "❓ Daily SLO Summary - UNKNOWN"
            description = f"**SLO Status: {status}** - Unable to determine status\n\n"
            description += "**Key Stats:**\n"
            description += f"• P95 Latency: {p95_latency:.1f}ms\n"
            description += f"• Stream Lag P95: {stream_lag_p95:.1f}s\n"
            description += f"• Uptime: {uptime_ratio:.1%}\n"
            description += f"• Dup Rate: {dup_rate:.2%}\n"
            description += f"• Window: {window_hours}h\n\n"
            description += "**Action:** Check SLO tracker status."
            
            _send_alert_if_not_cooldown(
                "daily_slo_summary",
                title,
                description,
                "WARN",
                **tags
            )
            
    except Exception as e:
        logger.error(f"Failed to send daily SLO alert: {e}")


async def run_alert_daemon(redis_client, config: Dict[str, Any]) -> None:
    """
    Run the alert daemon that periodically checks all alert rules.
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    logger.info("Starting alert daemon...")
    logger.info(f"Alert thresholds: no_signals={ALERT_NO_SIGNALS_MIN}min, redis_errors={ALERT_REDIS_ERRORS_PER_MIN}/min")
    logger.info(f"Debounce cooldown: {ALERT_DEBOUNCE_MIN}min")
    
    check_interval = 30  # Check every 30 seconds
    
    while True:
        try:
            logger.debug("Running alert rule checks...")
            
            # Run all alert rules concurrently
            await asyncio.gather(
                _check_no_signals_rule(redis_client, config),
                _check_heartbeat_rule(redis_client, config),
                _check_redis_errors_rule(redis_client, config),
                _check_daily_slo_summary(redis_client, config),
                return_exceptions=True
            )
            
            logger.debug("Alert rule checks completed")
            
        except Exception as e:
            logger.error(f"Error in alert daemon: {e}")
        
        # Wait for next check
        await asyncio.sleep(check_interval)


async def test_alert_rules(redis_client, config: Dict[str, Any]) -> None:
    """
    Test all alert rules once (for testing purposes).
    
    Args:
        redis_client: Redis client
        config: Configuration dictionary
    """
    print("Testing alert rules...")
    
    print("\\n1. Testing no signals rule...")
    await _check_no_signals_rule(redis_client, config)
    
    print("\\n2. Testing heartbeat rule...")
    await _check_heartbeat_rule(redis_client, config)
    
    print("\\n3. Testing Redis errors rule...")
    await _check_redis_errors_rule(redis_client, config)
    
    print("\\n4. Testing daily SLO summary rule...")
    await _check_daily_slo_summary(redis_client, config)
    
    print("\\nAlert rules test completed!")


if __name__ == "__main__":
    # Example usage and testing
    import redis
    
    async def main():
        # Connect to Redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        redis_client = redis.from_url(redis_url)
        
        # Test configuration
        config = {
            "mode": "staging"
        }
        
        try:
            # Test alert rules once
            await test_alert_rules(redis_client, config)
            
            # Uncomment to run daemon
            # await run_alert_daemon(redis_client, config)
            
        finally:
            if hasattr(redis_client, 'close'):
                await redis_client.close()
    
    asyncio.run(main())
