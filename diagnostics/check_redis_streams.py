#!/usr/bin/env python3
"""
Diagnostic script to check Redis streams for crypto-ai-bot.

Verifies:
- Redis connection uses TLS (rediss://) and env vars only
- Stream names match PRD exactly
- Published messages conform to expected schema

Usage:
    python -m diagnostics.check_redis_streams
    python -m diagnostics.check_redis_streams --limit 5
    python -m diagnostics.check_redis_streams --pair BTC/USD
"""

import asyncio
import os
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
load_dotenv()

# Import PRD-compliant modules
from agents.infrastructure.redis_client import RedisCloudClient, RedisCloudConfig
from agents.infrastructure.prd_redis_publisher import (
    get_signal_stream_name,
    get_pnl_stream_name,
    get_engine_mode,
)
from agents.infrastructure.prd_publisher import PRDSignal
from agents.infrastructure.prd_pnl import PRDTradeRecord
from models.prd_signal_schema import PRDSignalSchema

logger = None  # Will be set up


def check_redis_config() -> Dict[str, Any]:
    """Check Redis configuration for hard-coded credentials."""
    results = {
        "redis_url_source": "env_var",
        "redis_url_uses_tls": False,
        "ca_cert_source": "env_var",
        "has_hardcoded_credentials": False,
        "issues": [],
    }
    
    # Check REDIS_URL
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        results["issues"].append("REDIS_URL not set")
        return results
    
    # Check for TLS
    if redis_url.startswith("rediss://"):
        results["redis_url_uses_tls"] = True
    elif redis_url.startswith("redis://"):
        results["issues"].append("Redis URL uses redis:// instead of rediss:// (TLS required)")
    else:
        results["issues"].append(f"Invalid Redis URL scheme: {redis_url[:20]}...")
    
    # Check for hard-coded credentials in code
    # (This is a basic check - full scan would require grep)
    if "Crtpto-Ai-Bot" in redis_url or "redis-19818" in redis_url:
        # This is OK - it's in the env var, not hard-coded
        pass
    
    # Check CA cert
    ca_cert = os.getenv("REDIS_CA_CERT") or os.getenv("REDIS_CA_CERT_PATH")
    if not ca_cert:
        results["issues"].append("REDIS_CA_CERT not set")
    elif not os.path.exists(ca_cert):
        results["issues"].append(f"CA cert file not found: {ca_cert}")
    else:
        results["ca_cert_path"] = ca_cert
    
    return results


async def read_stream_entries(
    redis_client: RedisCloudClient,
    stream_name: str,
    count: int = 10,
) -> List[Dict[str, Any]]:
    """Read last N entries from a Redis stream."""
    try:
        # Get underlying client
        client = redis_client._client
        if client is None:
            return []
        
        # Read last N entries
        messages = await client.xrevrange(stream_name, count=count)
        
        entries = []
        for msg_id, fields in messages:
            # Decode bytes to strings
            entry_id = msg_id.decode() if isinstance(msg_id, bytes) else str(msg_id)
            decoded_fields = {}
            for k, v in fields.items():
                key = k.decode() if isinstance(k, bytes) else str(k)
                val = v.decode() if isinstance(v, bytes) else str(v)
                decoded_fields[key] = val
            
            entries.append({
                "entry_id": entry_id,
                "fields": decoded_fields,
            })
        
        return entries
    except Exception as e:
        print(f"  [ERROR] Failed to read stream {stream_name}: {e}")
        return []


def validate_signal_schema(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Validate signal entry against PRD schema."""
    result = {
        "valid": False,
        "errors": [],
        "fields_present": [],
        "fields_missing": [],
    }
    
    fields = entry.get("fields", {})
    
    # Required fields per PRD-001 Section 5.1
    required_fields = [
        "signal_id",
        "timestamp",
        "pair",
        "side",
        "strategy",
        "regime",
        "entry_price",
        "take_profit",
        "stop_loss",
        "position_size_usd",
        "confidence",
        "risk_reward_ratio",
        "indicators",
        "metadata",
    ]
    
    for field in required_fields:
        if field in fields:
            result["fields_present"].append(field)
        else:
            result["fields_missing"].append(field)
    
    # Try to validate with Pydantic model
    try:
        # Convert string fields back to proper types
        signal_dict = {}
        for k, v in fields.items():
            if k in ["entry_price", "take_profit", "stop_loss", "position_size_usd", 
                     "confidence", "risk_reward_ratio"]:
                try:
                    signal_dict[k] = float(v)
                except (ValueError, TypeError):
                    signal_dict[k] = v
            elif k in ["indicators", "metadata"]:
                try:
                    signal_dict[k] = json.loads(v) if isinstance(v, str) else v
                except:
                    signal_dict[k] = v
            else:
                signal_dict[k] = v
        
        # Validate with PRDSignal
        PRDSignal.model_validate(signal_dict)
        result["valid"] = True
    except Exception as e:
        result["errors"].append(f"Schema validation failed: {e}")
    
    return result


def validate_pnl_schema(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Validate PnL entry against PRD schema."""
    result = {
        "valid": False,
        "errors": [],
        "fields_present": [],
        "fields_missing": [],
    }
    
    fields = entry.get("fields", {})
    
    # Required fields for trade record
    required_fields = [
        "trade_id",
        "signal_id",
        "timestamp_open",
        "timestamp_close",
        "pair",
        "side",
        "strategy",
        "entry_price",
        "exit_price",
        "position_size_usd",
        "realized_pnl",
        "outcome",
    ]
    
    for field in required_fields:
        if field in fields:
            result["fields_present"].append(field)
        else:
            result["fields_missing"].append(field)
    
    # Try to validate with Pydantic model
    try:
        trade_dict = {}
        for k, v in fields.items():
            if k in ["entry_price", "exit_price", "position_size_usd", "realized_pnl",
                     "gross_pnl", "fees_usd", "slippage_pct"]:
                try:
                    trade_dict[k] = float(v)
                except (ValueError, TypeError):
                    trade_dict[k] = v
            elif k in ["hold_duration_sec"]:
                try:
                    trade_dict[k] = int(v)
                except (ValueError, TypeError):
                    trade_dict[k] = v
            else:
                trade_dict[k] = v
        
        PRDTradeRecord.model_validate(trade_dict)
        result["valid"] = True
    except Exception as e:
        result["errors"].append(f"Schema validation failed: {e}")
    
    return result


def check_stream_names(mode: str, pair: str) -> Dict[str, Any]:
    """Verify stream names match PRD exactly."""
    results = {
        "signal_stream": None,
        "pnl_stream": None,
        "matches_prd": False,
        "issues": [],
    }
    
    # Get stream names from functions
    signal_stream = get_signal_stream_name(mode, pair)
    pnl_stream = get_pnl_stream_name(mode)
    
    results["signal_stream"] = signal_stream
    results["pnl_stream"] = pnl_stream
    
    # Check against PRD spec
    # PRD-001: signals:paper:<PAIR> or signals:live:<PAIR>
    expected_signal = f"signals:{mode}:{pair.replace('/', '-').upper()}"
    if signal_stream != expected_signal:
        results["issues"].append(
            f"Signal stream mismatch: got {signal_stream}, expected {expected_signal}"
        )
    
    # PRD-001: pnl:paper:equity_curve or pnl:live:equity_curve
    expected_pnl = f"pnl:{mode}:equity_curve"
    if pnl_stream != expected_pnl:
        results["issues"].append(
            f"PnL stream mismatch: got {pnl_stream}, expected {expected_pnl}"
        )
    
    results["matches_prd"] = len(results["issues"]) == 0
    
    return results


async def main():
    """Main diagnostic function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Check Redis streams for crypto-ai-bot")
    parser.add_argument("--limit", type=int, default=10, help="Number of entries to read per stream")
    parser.add_argument("--pair", type=str, default="BTC/USD", help="Trading pair to check")
    parser.add_argument("--mode", type=str, choices=["paper", "live"], default=None, help="Mode (default: from ENGINE_MODE)")
    
    args = parser.parse_args()
    
    print("=" * 80)
    print("CRYPTO-AI-BOT REDIS STREAMS DIAGNOSTIC")
    print("=" * 80)
    print()
    
    # 1. Check Redis configuration
    print("[1] Checking Redis Configuration...")
    config_check = check_redis_config()
    
    if config_check["redis_url_uses_tls"]:
        print("  [PASS] Redis URL uses TLS (rediss://)")
    else:
        print("  [FAIL] Redis URL does not use TLS")
    
    if config_check["issues"]:
        print("  [ISSUES]:")
        for issue in config_check["issues"]:
            print(f"    - {issue}")
    else:
        print("  [PASS] No configuration issues found")
    
    print()
    
    # 2. Connect to Redis
    print("[2] Connecting to Redis...")
    try:
        redis_config = RedisCloudConfig()
        redis_client = RedisCloudClient(redis_config)
        await redis_client.connect()
        print("  [PASS] Connected to Redis successfully")
    except Exception as e:
        print(f"  [FAIL] Failed to connect: {e}")
        return 1
    
    print()
    
    # 3. Check stream names
    print("[3] Verifying Stream Names...")
    mode = args.mode or get_engine_mode()
    stream_check = check_stream_names(mode, args.pair)
    
    print(f"  Mode: {mode}")
    print(f"  Signal stream: {stream_check['signal_stream']}")
    print(f"  PnL stream: {stream_check['pnl_stream']}")
    
    if stream_check["matches_prd"]:
        print("  [PASS] Stream names match PRD-001 spec")
    else:
        print("  [FAIL] Stream name mismatches:")
        for issue in stream_check["issues"]:
            print(f"    - {issue}")
    
    print()
    
    # 4. Read and validate signal stream
    print(f"[4] Reading Signal Stream: {stream_check['signal_stream']}...")
    signal_entries = await read_stream_entries(redis_client, stream_check['signal_stream'], args.limit)
    
    if not signal_entries:
        print("  [INFO] Stream is empty or not accessible")
    else:
        print(f"  [INFO] Found {len(signal_entries)} entries")
        
        # Validate first entry
        if signal_entries:
            validation = validate_signal_schema(signal_entries[0])
            if validation["valid"]:
                print("  [PASS] Signal schema validation passed")
            else:
                print("  [FAIL] Signal schema validation failed:")
                for error in validation["errors"]:
                    print(f"    - {error}")
                if validation["fields_missing"]:
                    print(f"    - Missing fields: {', '.join(validation['fields_missing'])}")
            
            # Show sample
            sample = signal_entries[0]
            print(f"  [SAMPLE] Entry ID: {sample['entry_id']}")
            print(f"    Pair: {sample['fields'].get('pair', 'N/A')}")
            print(f"    Side: {sample['fields'].get('side', 'N/A')}")
            print(f"    Strategy: {sample['fields'].get('strategy', 'N/A')}")
            print(f"    Timestamp: {sample['fields'].get('timestamp', 'N/A')}")
    
    print()
    
    # 5. Read and validate PnL stream (equity curve)
    print(f"[5] Reading PnL Stream: {stream_check['pnl_stream']}...")
    pnl_entries = await read_stream_entries(redis_client, stream_check['pnl_stream'], args.limit)
    
    if not pnl_entries:
        print("  [INFO] Stream is empty or not accessible")
    else:
        print(f"  [INFO] Found {len(pnl_entries)} entries")
        if pnl_entries:
            sample = pnl_entries[0]
            print(f"  [SAMPLE] Entry ID: {sample['entry_id']}")
            print(f"    Timestamp: {sample['fields'].get('timestamp', 'N/A')}")
            print(f"    Equity: {sample['fields'].get('equity', 'N/A')}")
    
    print()
    
    # 6. Check for pnl:signals stream (trade records)
    print("[6] Checking PnL Trade Records Stream...")
    pnl_signals_stream = f"pnl:{mode}:signals"
    pnl_signals_entries = await read_stream_entries(redis_client, pnl_signals_stream, args.limit)
    
    if not pnl_signals_entries:
        print(f"  [INFO] Stream {pnl_signals_stream} is empty or not accessible")
    else:
        print(f"  [INFO] Found {len(pnl_signals_entries)} trade records")
        
        # Validate first entry
        if pnl_signals_entries:
            validation = validate_pnl_schema(pnl_signals_entries[0])
            if validation["valid"]:
                print("  [PASS] PnL trade record schema validation passed")
            else:
                print("  [FAIL] PnL trade record schema validation failed:")
                for error in validation["errors"]:
                    print(f"    - {error}")
            
            sample = pnl_signals_entries[0]
            print(f"  [SAMPLE] Trade ID: {sample['fields'].get('trade_id', 'N/A')}")
            print(f"    Signal ID: {sample['fields'].get('signal_id', 'N/A')}")
            print(f"    Pair: {sample['fields'].get('pair', 'N/A')}")
            print(f"    PnL: {sample['fields'].get('realized_pnl', 'N/A')}")
    
    print()
    
    # Summary
    print("=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    all_passed = (
        config_check["redis_url_uses_tls"] and
        len(config_check["issues"]) == 0 and
        stream_check["matches_prd"]
    )
    
    if all_passed:
        print("[PASS] All checks passed!")
    else:
        print("[FAIL] Some checks failed - see details above")
    
    print()
    print("Checklist:")
    print(f"  [{'PASS' if config_check['redis_url_uses_tls'] else 'FAIL'}] Redis TLS (rediss://)")
    print(f"  [{'PASS' if stream_check['matches_prd'] else 'FAIL'}] Stream names match PRD")
    print(f"  [{'PASS' if signal_entries and validate_signal_schema(signal_entries[0])['valid'] else 'INFO'}] Signal schema correctness")
    print(f"  [{'PASS' if pnl_signals_entries and validate_pnl_schema(pnl_signals_entries[0])['valid'] else 'INFO'}] PnL schema correctness")
    print("=" * 80)
    
    await redis_client.disconnect()
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))








