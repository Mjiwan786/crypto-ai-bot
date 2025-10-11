#!/usr/bin/env python3
"""
Crypto AI Bot Operations MCP Server

Provides operational tools for monitoring and managing the crypto trading bot.
Supports subcommands: emit-policy, metrics, status

Usage:
    python ops_mcp.py emit-policy --note "Risk policy updated"
    python ops_mcp.py metrics
    python ops_mcp.py status
"""

import argparse
import json
import os
import sys
import time
import hashlib
import socket
from datetime import datetime
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from contextlib import suppress

# Optional: Redis support
with suppress(Exception):
    import redis
    from urllib.parse import urlparse
    import ssl

class Health(BaseModel):
    component: str = Field(default="mcp")
    status: str
    hostname: str = Field(default_factory=socket.gethostname)
    ts: float = Field(default_factory=lambda: time.time())

class PolicyNote(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    note: str
    hostname: str = Field(default_factory=socket.gethostname)
    user: str = Field(default_factory=lambda: os.getenv("USER", "unknown"))

class SystemStatus(BaseModel):
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    hostname: str = Field(default_factory=socket.gethostname)
    redis_status: str
    python_version: str = Field(default_factory=lambda: sys.version.split()[0])
    environment: str = Field(default_factory=lambda: os.getenv("ENVIRONMENT", "unknown"))
    uptime_seconds: float = Field(default_factory=lambda: time.time() - start_time)

# Global start time for uptime calculation
start_time = time.time()

def validate_redis_url() -> bool:
    """Validate REDIS_URL environment variable"""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("ERROR: REDIS_URL environment variable not set", file=sys.stderr)
        return False
    
    try:
        parsed = urlparse(redis_url)
        if parsed.scheme not in ["redis", "rediss"]:
            print(f"ERROR: Invalid Redis URL scheme: {parsed.scheme}", file=sys.stderr)
            return False
        return True
    except Exception as e:
        print(f"ERROR: Invalid REDIS_URL: {e}", file=sys.stderr)
        return False

def get_redis_client() -> Optional[redis.Redis]:
    """Get Redis client with proper TLS configuration"""
    if not validate_redis_url():
        return None
    
    redis_url = os.getenv("REDIS_URL")
    parsed = urlparse(redis_url)
    use_ssl = parsed.scheme == "rediss"
    
    try:
        if use_ssl:
            ssl_context = ssl.create_default_context()
            ca_cert_path = os.getenv("REDIS_TLS_CERT_PATH", "/etc/ssl/certs/ca-certificates.crt")
            
            if os.path.exists(ca_cert_path):
                ssl_context.load_verify_locations(ca_cert_path)
            
            return redis.from_url(
                redis_url,
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                ssl_ca_certs=ca_cert_path,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
        else:
            return redis.from_url(
                redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
    except Exception as e:
        print(f"ERROR: Failed to connect to Redis: {e}", file=sys.stderr)
        return None

def emit_policy_command(args) -> int:
    """Emit policy note to Redis stream"""
    print("📝 Emitting policy note to Redis...")
    
    client = get_redis_client()
    if not client:
        return 1
    
    try:
        # Test connection
        client.ping()
        
        # Create policy note
        policy = PolicyNote(note=args.note)
        policy_data = policy.model_dump()
        
        # Push to Redis stream
        stream_name = "ops:policy"
        message_id = client.xadd(stream_name, policy_data)
        
        print(f"✅ Policy note emitted successfully")
        print(f"   Stream: {stream_name}")
        print(f"   Message ID: {message_id}")
        print(f"   Note: {args.note}")
        
        return 0
        
    except Exception as e:
        print(f"❌ Failed to emit policy note: {e}", file=sys.stderr)
        return 1

def metrics_command(args) -> int:
    """Read metrics snapshot from Redis"""
    print("📊 Reading metrics snapshot...")
    
    client = get_redis_client()
    if not client:
        return 1
    
    try:
        # Test connection
        client.ping()
        
        # Read metrics from various streams
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "redis_status": "connected",
            "streams": {}
        }
        
        # Read from common metric streams
        metric_streams = [
            "metrics:signals",
            "metrics:performance", 
            "metrics:health",
            "ops:policy"
        ]
        
        for stream_name in metric_streams:
            try:
                # Get latest messages from stream
                messages = client.xrevrange(stream_name, count=10)
                if messages:
                    metrics["streams"][stream_name] = {
                        "message_count": len(messages),
                        "latest_message": messages[0][1] if messages else None
                    }
                else:
                    metrics["streams"][stream_name] = {
                        "message_count": 0,
                        "latest_message": None
                    }
            except redis.RedisError:
                metrics["streams"][stream_name] = {
                    "message_count": 0,
                    "latest_message": None,
                    "error": "Stream not found or inaccessible"
                }
        
        # Output JSON
        print(json.dumps(metrics, indent=2))
        return 0
        
    except Exception as e:
        print(f"❌ Failed to read metrics: {e}", file=sys.stderr)
        return 1

def status_command(args) -> int:
    """Print system status JSON"""
    print("🔍 Checking system status...")
    
    # Basic system status
    status = SystemStatus(
        redis_status="unknown",
        python_version=sys.version.split()[0],
        environment=os.getenv("ENVIRONMENT", "unknown")
    )
    
    # Check Redis status
    client = get_redis_client()
    if client:
        try:
            start_time = time.time()
            client.ping()
            latency = (time.time() - start_time) * 1000
            status.redis_status = f"connected (latency: {latency:.2f}ms)"
        except Exception as e:
            status.redis_status = f"error: {str(e)}"
    else:
        status.redis_status = "not_configured"
    
    # Add additional system info
    status_dict = status.model_dump()
    status_dict.update({
        "config": {
            "redis_url_configured": bool(os.getenv("REDIS_URL")),
            "environment": os.getenv("ENVIRONMENT", "unknown"),
            "log_level": os.getenv("LOG_LEVEL", "INFO")
        },
        "files": {}
    })
    
    # Check key files
    key_files = ["main.py", "pyproject.toml", "requirements.txt", "docker-compose.yml"]
    for file_path in key_files:
        if os.path.exists(file_path):
            try:
                stat = os.stat(file_path)
                status_dict["files"][file_path] = {
                    "exists": True,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                }
            except Exception:
                status_dict["files"][file_path] = {"exists": True, "error": "stat_failed"}
        else:
            status_dict["files"][file_path] = {"exists": False}
    
    # Output JSON
    print(json.dumps(status_dict, indent=2))
    return 0

def cli():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot Operations MCP Server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ops_mcp.py emit-policy --note "Risk policy updated"
  python ops_mcp.py metrics
  python ops_mcp.py status
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Emit policy subcommand
    emit_parser = subparsers.add_parser("emit-policy", help="Emit policy note to Redis")
    emit_parser.add_argument("--note", required=True, help="Policy note to emit")
    
    # Metrics subcommand
    metrics_parser = subparsers.add_parser("metrics", help="Read metrics snapshot from Redis")
    
    # Status subcommand
    status_parser = subparsers.add_parser("status", help="Print system status JSON")
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return 1
    
    # Run appropriate command
    if args.command == "emit-policy":
        return emit_policy_command(args)
    elif args.command == "metrics":
        return metrics_command(args)
    elif args.command == "status":
        return status_command(args)
    else:
        parser.print_help()
        return 1

if __name__ == "__main__":
    sys.exit(cli())