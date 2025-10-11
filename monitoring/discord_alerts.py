"""
Discord Alerts System

This module provides Discord webhook integration for sending operational alerts
to the crypto AI bot operations channel.

Usage:
    from monitoring.discord_alerts import send_alert
    send_alert("System Alert", "Bot is running low on memory", "WARN", {"component": "memory"})
"""

import os
import logging
import requests
from typing import Optional, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Environment configuration
DISCORD_OPS_WEBHOOK_URL = os.getenv("DISCORD_OPS_WEBHOOK_URL")

# Global state for error handling
_webhook_configured = False
_error_logged = False

# Severity color mapping (Discord embed colors)
SEVERITY_COLORS = {
    "INFO": 0x00ff00,      # Green
    "WARN": 0xffaa00,      # Orange
    "ERROR": 0xff0000,     # Red
    "CRITICAL": 0x8b0000,  # Dark red
    "SUCCESS": 0x00ff00,   # Green
    "DEBUG": 0x808080,     # Gray
}

# Default severity if not specified
DEFAULT_SEVERITY = "WARN"


def _get_webhook_url() -> Optional[str]:
    """Get the Discord webhook URL from environment."""
    global _webhook_configured, _error_logged
    
    if not DISCORD_OPS_WEBHOOK_URL:
        if not _error_logged:
            logger.warning("DISCORD_OPS_WEBHOOK_URL not configured - Discord alerts disabled")
            _error_logged = True
        return None
    
    if not _webhook_configured:
        logger.info("Discord webhook configured - alerts enabled")
        _webhook_configured = True
    
    return DISCORD_OPS_WEBHOOK_URL


def _format_tags(tags: Optional[Dict[str, Any]]) -> str:
    """Format tags dictionary into a readable string."""
    if not tags:
        return ""
    
    tag_lines = []
    for key, value in tags.items():
        # Truncate long values to prevent Discord embed limits
        if isinstance(value, str) and len(value) > 50:
            value = value[:47] + "..."
        tag_lines.append(f"**{key}**: {value}")
    
    return "\\n".join(tag_lines)


def _create_embed(title: str, description: str, severity: str, tags: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Create a Discord embed object."""
    # Normalize severity
    severity = severity.upper() if severity else DEFAULT_SEVERITY
    color = SEVERITY_COLORS.get(severity, SEVERITY_COLORS[DEFAULT_SEVERITY])
    
    # Create embed
    embed = {
        "title": title,
        "description": description,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {
            "text": f"crypto-ai-bot • {severity}"
        }
    }
    
    # Add tags if provided
    if tags:
        embed["fields"] = [{
            "name": "Tags",
            "value": _format_tags(tags),
            "inline": False
        }]
    
    return embed


def send_alert(
    title: str, 
    description: str, 
    severity: str = "WARN", 
    tags: Optional[Dict[str, Any]] = None
) -> bool:
    """
    Send an alert to the Discord operations channel.
    
    Args:
        title: Alert title
        description: Alert description
        severity: Alert severity (INFO, WARN, ERROR, CRITICAL, SUCCESS, DEBUG)
        tags: Optional dictionary of key-value tags
        
    Returns:
        True if alert was sent successfully, False otherwise
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        return False
    
    try:
        # Create the embed
        embed = _create_embed(title, description, severity, tags)
        
        # Prepare payload
        payload = {
            "embeds": [embed],
            "username": "crypto-ai-bot",
            "avatar_url": "https://cdn.discordapp.com/embed/avatars/0.png"  # Default bot avatar
        }
        
        # Send to Discord
        response = requests.post(
            webhook_url,
            json=payload,
            timeout=5,
            headers={"Content-Type": "application/json"}
        )
        
        # Check response
        if response.status_code == 204:
            logger.debug(f"Discord alert sent: {title} ({severity})")
            return True
        else:
            logger.warning(f"Discord webhook returned status {response.status_code}: {response.text}")
            return False
            
    except requests.exceptions.Timeout:
        logger.warning("Discord webhook timeout - alert not sent")
        return False
    except requests.exceptions.RequestException as e:
        logger.warning(f"Discord webhook request failed: {e}")
        return False
    except Exception as e:
        logger.warning(f"Unexpected error sending Discord alert: {e}")
        return False


def send_system_alert(component: str, message: str, severity: str = "WARN", **kwargs) -> bool:
    """
    Send a system component alert with standardized formatting.
    
    Args:
        component: System component name (e.g., "redis", "kraken", "signals")
        message: Alert message
        severity: Alert severity
        **kwargs: Additional tags
        
    Returns:
        True if alert was sent successfully, False otherwise
    """
    title = f"System Alert: {component.upper()}"
    tags = {"component": component, **kwargs}
    
    return send_alert(title, message, severity, tags)


def send_trading_alert(symbol: str, message: str, severity: str = "INFO", **kwargs) -> bool:
    """
    Send a trading-related alert with standardized formatting.
    
    Args:
        symbol: Trading symbol (e.g., "BTC/USD")
        message: Alert message
        severity: Alert severity
        **kwargs: Additional tags
        
    Returns:
        True if alert was sent successfully, False otherwise
    """
    title = f"Trading Alert: {symbol}"
    tags = {"symbol": symbol, **kwargs}
    
    return send_alert(title, message, severity, tags)


def send_metrics_alert(metric: str, value: Any, threshold: Any, severity: str = "WARN", **kwargs) -> bool:
    """
    Send a metrics-based alert with standardized formatting.
    
    Args:
        metric: Metric name
        value: Current metric value
        threshold: Threshold that was exceeded
        severity: Alert severity
        **kwargs: Additional tags
        
    Returns:
        True if alert was sent successfully, False otherwise
    """
    title = f"Metrics Alert: {metric}"
    description = f"Current value: {value} (threshold: {threshold})"
    tags = {"metric": metric, "value": str(value), "threshold": str(threshold), **kwargs}
    
    return send_alert(title, description, severity, tags)


def test_discord_webhook() -> bool:
    """
    Test the Discord webhook configuration.
    
    Returns:
        True if webhook is working, False otherwise
    """
    return send_alert(
        "Test Alert", 
        "Hello from crypto-ai-bot - Discord integration is working!", 
        "INFO",
        {"test": "true", "timestamp": datetime.now(timezone.utc).isoformat()}
    )


# Convenience functions for common alert types
def alert_redis_down() -> bool:
    """Alert that Redis is down."""
    return send_system_alert("redis", "Redis connection lost", "ERROR")

def alert_redis_recovered() -> bool:
    """Alert that Redis has recovered."""
    return send_system_alert("redis", "Redis connection restored", "SUCCESS")

def alert_kraken_disconnect() -> bool:
    """Alert that Kraken WebSocket disconnected."""
    return send_system_alert("kraken", "Kraken WebSocket disconnected", "WARN")

def alert_kraken_reconnected() -> bool:
    """Alert that Kraken WebSocket reconnected."""
    return send_system_alert("kraken", "Kraken WebSocket reconnected", "SUCCESS")

def alert_signal_published(symbol: str, strategy: str) -> bool:
    """Alert that a signal was published."""
    return send_trading_alert(symbol, f"Signal published by {strategy}", "INFO", strategy=strategy)

def alert_high_latency(component: str, latency_ms: float, threshold_ms: float) -> bool:
    """Alert about high latency."""
    return send_metrics_alert(
        f"{component}_latency", 
        f"{latency_ms:.1f}ms", 
        f"{threshold_ms}ms", 
        "WARN",
        component=component
    )


if __name__ == "__main__":
    # Test the Discord webhook
    print("Testing Discord webhook...")
    
    # Test basic alert
    success = test_discord_webhook()
    if success:
        print("✅ Discord webhook test successful!")
    else:
        print("❌ Discord webhook test failed - check configuration")
    
    # Test various alert types
    print("\\nTesting alert types...")
    send_system_alert("test", "System component test", "INFO", version="1.0.0")
    send_trading_alert("BTC/USD", "Test trading alert", "INFO", price="50000")
    send_metrics_alert("cpu_usage", "85%", "80%", "WARN", server="prod-01")
    
    print("Discord alerts test completed!")
