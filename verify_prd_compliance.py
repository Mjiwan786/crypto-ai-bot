#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Week 2 Verification Script: Verify PRD-001 Compliant Signals & PnL Publishing

This script verifies that the crypto-ai-bot is publishing:
1. PRD-001 compliant signals to signals:paper:<PAIR> streams
2. PnL data to pnl:paper:equity_curve stream
3. All required fields are present and valid

Usage:
    conda activate crypto-bot
    python verify_prd_compliance.py
"""

import asyncio
import os
import sys
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        # Python < 3.7
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer, 'strict')
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer, 'strict')

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    import redis.asyncio as redis
    from dotenv import load_dotenv
except ImportError as e:
    print(f"ERROR: Missing required package: {e}")
    print("Please install: pip install redis python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv(".env.paper", override=False)
load_dotenv(".env.prod", override=False)

# PRD-001 Required Signal Fields (Section 5.1)
REQUIRED_SIGNAL_FIELDS = {
    "signal_id": str,
    "timestamp": str,
    "pair": str,
    "side": str,
    "strategy": str,
    "regime": str,
    "entry_price": float,
    "take_profit": float,
    "stop_loss": float,
    "position_size_usd": float,
    "confidence": float,
    "risk_reward_ratio": float,
}

# Optional nested fields
OPTIONAL_NESTED_FIELDS = {
    "indicators": {
        "rsi_14": float,
        "macd_signal": str,
        "atr_14": float,
        "volume_ratio": float,
    },
    "metadata": {
        "model_version": str,
        "backtest_sharpe": float,
        "latency_ms": int,
    }
}

# Valid enum values
VALID_SIDES = {"LONG", "SHORT"}
VALID_STRATEGIES = {"SCALPER", "TREND", "MEAN_REVERSION", "BREAKOUT"}
VALID_REGIMES = {"TRENDING_UP", "TRENDING_DOWN", "RANGING", "VOLATILE"}
VALID_MACD_SIGNALS = {"BULLISH", "BEARISH", "NEUTRAL"}

# Trading pairs to check
TRADING_PAIRS = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]


class PRDComplianceChecker:
    """Verifies PRD-001 compliance for signals and PnL"""

    def __init__(self):
        self.redis_url = os.getenv("REDIS_URL")
        self.redis_ca_cert = os.getenv(
            "REDIS_CA_CERT",
            os.getenv("REDIS_CA_CERT_PATH", "config/certs/redis_ca.pem")
        )
        self.mode = os.getenv("ENGINE_MODE", "paper")
        self.redis_client: Optional[redis.Redis] = None
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.successes: List[str] = []

    async def connect(self) -> bool:
        """Connect to Redis Cloud with TLS"""
        try:
            if not self.redis_url:
                self.errors.append("REDIS_URL environment variable not set")
                return False

            if not os.path.exists(self.redis_ca_cert):
                self.warnings.append(
                    f"CA certificate not found at {self.redis_ca_cert}, "
                    "TLS connection may fail"
                )
                # Try alternative path
                alt_path = project_root / "config" / "certs" / "redis_ca.pem"
                if alt_path.exists():
                    self.redis_ca_cert = str(alt_path)

            self.redis_client = redis.from_url(
                self.redis_url,
                ssl_cert_reqs='required',
                ssl_ca_certs=self.redis_ca_cert if os.path.exists(self.redis_ca_cert) else None,
                decode_responses=True,
                socket_connect_timeout=10,
                socket_timeout=10,
            )

            await self.redis_client.ping()
            self.successes.append("[OK] Connected to Redis Cloud successfully")
            return True

        except Exception as e:
            self.errors.append(f"[ERROR] Failed to connect to Redis: {e}")
            return False

    async def disconnect(self):
        """Disconnect from Redis"""
        if self.redis_client:
            try:
                await self.redis_client.aclose()
            except Exception:
                pass  # Ignore errors during disconnect

    def validate_signal_schema(self, signal_data: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        Validate signal against PRD-001 schema requirements.

        Returns:
            (is_valid, list_of_errors)
        """
        errors = []

        # Check required fields
        for field, field_type in REQUIRED_SIGNAL_FIELDS.items():
            if field not in signal_data:
                errors.append(f"Missing required field: {field}")
                continue

            value = signal_data[field]

            # Type validation
            if field_type == str:
                if not isinstance(value, str):
                    errors.append(f"Field {field} must be string, got {type(value).__name__}")
            elif field_type == float:
                try:
                    float(value)
                except (ValueError, TypeError):
                    errors.append(f"Field {field} must be float, got {type(value).__name__}")

        # Validate enum values
        if "side" in signal_data:
            side = signal_data["side"].upper()
            if side not in VALID_SIDES:
                errors.append(f"Invalid side: {side}. Must be one of {VALID_SIDES}")

        if "strategy" in signal_data:
            strategy = signal_data["strategy"].upper()
            if strategy not in VALID_STRATEGIES:
                errors.append(f"Invalid strategy: {strategy}. Must be one of {VALID_STRATEGIES}")

        if "regime" in signal_data:
            regime = signal_data["regime"].upper()
            if regime not in VALID_REGIMES:
                errors.append(f"Invalid regime: {regime}. Must be one of {VALID_REGIMES}")

        # Validate numeric ranges
        if "confidence" in signal_data:
            try:
                conf = float(signal_data["confidence"])
                if not (0.0 <= conf <= 1.0):
                    errors.append(f"Confidence must be in [0.0, 1.0], got {conf}")
            except (ValueError, TypeError):
                pass  # Already caught in type validation

        if "position_size_usd" in signal_data:
            try:
                size = float(signal_data["position_size_usd"])
                if size <= 0:
                    errors.append(f"position_size_usd must be > 0, got {size}")
                if size > 2000:
                    errors.append(f"position_size_usd exceeds max (2000), got {size}")
            except (ValueError, TypeError):
                pass

        # Validate price relationships
        if all(k in signal_data for k in ["entry_price", "take_profit", "stop_loss", "side"]):
            try:
                entry = float(signal_data["entry_price"])
                tp = float(signal_data["take_profit"])
                sl = float(signal_data["stop_loss"])
                side = signal_data["side"].upper()

                if side == "LONG":
                    if tp <= entry:
                        errors.append(f"LONG: take_profit ({tp}) must be > entry_price ({entry})")
                    if sl >= entry:
                        errors.append(f"LONG: stop_loss ({sl}) must be < entry_price ({entry})")
                elif side == "SHORT":
                    if tp >= entry:
                        errors.append(f"SHORT: take_profit ({tp}) must be < entry_price ({entry})")
                    if sl <= entry:
                        errors.append(f"SHORT: stop_loss ({sl}) must be > entry_price ({entry})")
            except (ValueError, TypeError):
                pass

        # Validate timestamp format (ISO8601)
        if "timestamp" in signal_data:
            try:
                datetime.fromisoformat(signal_data["timestamp"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                errors.append(f"Invalid timestamp format: {signal_data['timestamp']}")

        # Validate signal_id (UUID format)
        if "signal_id" in signal_data:
            import uuid
            try:
                uuid.UUID(signal_data["signal_id"])
            except (ValueError, AttributeError):
                errors.append(f"Invalid signal_id format (not UUID): {signal_data['signal_id']}")

        return len(errors) == 0, errors

    async def check_signal_streams(self) -> Dict[str, Any]:
        """Check signals:paper:<PAIR> streams for PRD-compliant signals"""
        results = {
            "streams_found": [],
            "streams_empty": [],
            "streams_missing": [],
            "signals_valid": 0,
            "signals_invalid": 0,
            "sample_signals": [],
        }

        for pair in TRADING_PAIRS:
            # Convert pair format: BTC/USD -> BTC-USD for Redis stream key
            safe_pair = pair.replace("/", "-")
            stream_key = f"signals:{self.mode}:{safe_pair}"

            try:
                stream_len = await self.redis_client.xlen(stream_key)

                if stream_len == 0:
                    results["streams_empty"].append(stream_key)
                    continue

                results["streams_found"].append((stream_key, stream_len))

                # Get last 5 signals for validation
                entries = await self.redis_client.xrevrange(stream_key, "+", "-", count=5)

                for entry_id, fields in entries:
                    # Parse signal data
                    signal_data = {}
                    for key, value in fields.items():
                        # Handle nested fields (e.g., "indicators_rsi_14")
                        if "_" in key and key.startswith(("indicators_", "metadata_")):
                            # This is a flattened nested field
                            prefix, nested_key = key.split("_", 1)
                            if prefix not in signal_data:
                                signal_data[prefix] = {}
                            signal_data[prefix][nested_key] = value
                        else:
                            signal_data[key] = value

                    # Validate schema
                    is_valid, errors = self.validate_signal_schema(signal_data)

                    if is_valid:
                        results["signals_valid"] += 1
                        if len(results["sample_signals"]) < 3:
                            results["sample_signals"].append({
                                "stream": stream_key,
                                "entry_id": entry_id,
                                "signal": signal_data,
                            })
                    else:
                        results["signals_invalid"] += 1
                        self.warnings.append(
                            f"Invalid signal in {stream_key} (ID: {entry_id[:20]}...): {errors}"
                        )

            except Exception as e:
                results["streams_missing"].append((stream_key, str(e)))

        return results

    async def check_pnl_stream(self) -> Dict[str, Any]:
        """Check pnl:paper:equity_curve stream"""
        results = {
            "stream_exists": False,
            "stream_length": 0,
            "latest_entry": None,
            "sample_entries": [],
        }

        stream_key = f"pnl:{self.mode}:equity_curve"

        try:
            stream_len = await self.redis_client.xlen(stream_key)
            results["stream_length"] = stream_len
            results["stream_exists"] = True

            if stream_len > 0:
                # Get last 5 entries
                entries = await self.redis_client.xrevrange(stream_key, "+", "-", count=5)

                for entry_id, fields in entries:
                    entry_data = dict(fields)
                    results["sample_entries"].append({
                        "entry_id": entry_id,
                        "data": entry_data,
                    })

                if entries:
                    results["latest_entry"] = {
                        "entry_id": entries[0][0],
                        "data": dict(entries[0][1]),
                    }

        except Exception as e:
            self.errors.append(f"Failed to check PnL stream {stream_key}: {e}")

        return results

    async def check_telemetry_keys(self) -> Dict[str, Any]:
        """Check telemetry keys for signals-api/frontend"""
        results = {
            "keys_found": [],
            "keys_missing": [],
        }

        telemetry_keys = [
            f"engine:last_signal_meta",
            f"engine:last_pnl_meta",
        ]

        for key in telemetry_keys:
            try:
                value = await self.redis_client.get(key)
                if value:
                    results["keys_found"].append(key)
                    try:
                        parsed = json.loads(value)
                        results[key] = parsed
                    except json.JSONDecodeError:
                        results[key] = value
                else:
                    results["keys_missing"].append(key)
            except Exception as e:
                results["keys_missing"].append((key, str(e)))

        return results

    async def run_verification(self):
        """Run full PRD compliance verification"""
        print("=" * 80)
        print("PRD-001 COMPLIANCE VERIFICATION")
        print("=" * 80)
        print(f"Mode: {self.mode}")
        print(f"Redis URL: {self.redis_url[:50]}..." if self.redis_url else "Not set")
        print(f"CA Cert: {self.redis_ca_cert}")
        print()

        # Connect to Redis
        if not await self.connect():
            print("\n".join(self.errors))
            return

        print("\n" + "=" * 80)
        print("1. CHECKING SIGNAL STREAMS")
        print("=" * 80)

        signal_results = await self.check_signal_streams()

        print(f"\nStreams Found: {len(signal_results['streams_found'])}")
        for stream_key, length in signal_results["streams_found"]:
            print(f"  [OK] {stream_key}: {length} messages")

        if signal_results["streams_empty"]:
            print(f"\nEmpty Streams: {len(signal_results['streams_empty'])}")
            for stream_key in signal_results["streams_empty"]:
                print(f"  [WARN] {stream_key}: No messages")

        if signal_results["streams_missing"]:
            print(f"\nMissing/Error Streams: {len(signal_results['streams_missing'])}")
            for stream_key, error in signal_results["streams_missing"]:
                print(f"  [ERROR] {stream_key}: {error}")

        print(f"\nSignal Validation:")
        print(f"  [OK] Valid signals: {signal_results['signals_valid']}")
        print(f"  [ERROR] Invalid signals: {signal_results['signals_invalid']}")

        if signal_results["sample_signals"]:
            print(f"\nSample Valid Signals:")
            for i, sample in enumerate(signal_results["sample_signals"][:3], 1):
                print(f"\n  Sample {i}:")
                print(f"    Stream: {sample['stream']}")
                print(f"    Entry ID: {sample['entry_id']}")
                sig = sample["signal"]
                print(f"    Signal ID: {sig.get('signal_id', 'N/A')[:36]}")
                print(f"    Pair: {sig.get('pair', 'N/A')}")
                print(f"    Side: {sig.get('side', 'N/A')}")
                print(f"    Strategy: {sig.get('strategy', 'N/A')}")
                print(f"    Entry Price: ${float(sig.get('entry_price', 0)):.2f}")
                print(f"    Confidence: {float(sig.get('confidence', 0)):.2%}")
                print(f"    Timestamp: {sig.get('timestamp', 'N/A')}")

        print("\n" + "=" * 80)
        print("2. CHECKING PNL STREAM")
        print("=" * 80)

        pnl_results = await self.check_pnl_stream()
        stream_key = f"pnl:{self.mode}:equity_curve"

        if pnl_results["stream_exists"]:
            print(f"[OK] Stream exists: {stream_key}")
            print(f"   Length: {pnl_results['stream_length']} entries")

            if pnl_results["latest_entry"]:
                latest = pnl_results["latest_entry"]
                print(f"\nLatest PnL Entry:")
                print(f"  Entry ID: {latest['entry_id']}")
                data = latest["data"]
                print(f"  Timestamp: {data.get('timestamp', 'N/A')}")
                print(f"  Equity: ${float(data.get('equity', 0)):,.2f}")
                print(f"  Realized PnL: ${float(data.get('realized_pnl', 0)):,.2f}")
                print(f"  Unrealized PnL: ${float(data.get('unrealized_pnl', 0)):,.2f}")
                print(f"  Positions: {data.get('num_positions', 0)}")
        else:
            print(f"[ERROR] Stream not found or empty: {stream_key}")

        print("\n" + "=" * 80)
        print("3. CHECKING TELEMETRY KEYS")
        print("=" * 80)

        telemetry_results = await self.check_telemetry_keys()

        if telemetry_results["keys_found"]:
            print(f"[OK] Found telemetry keys: {len(telemetry_results['keys_found'])}")
            for key in telemetry_results["keys_found"]:
                if key in telemetry_results:
                    print(f"  {key}: {json.dumps(telemetry_results[key], indent=2)[:200]}...")
        else:
            print("[WARN] No telemetry keys found")

        if telemetry_results["keys_missing"]:
            print(f"\n[WARN] Missing telemetry keys: {len(telemetry_results['keys_missing'])}")
            for key in telemetry_results["keys_missing"]:
                if isinstance(key, tuple):
                    print(f"  {key[0]}: {key[1]}")
                else:
                    print(f"  {key}")

        # Summary
        print("\n" + "=" * 80)
        print("VERIFICATION SUMMARY")
        print("=" * 80)

        total_signals = signal_results["signals_valid"] + signal_results["signals_invalid"]
        has_signals = total_signals > 0
        has_pnl = pnl_results["stream_length"] > 0

        if has_signals and signal_results["signals_valid"] == total_signals:
            print("[OK] SIGNALS: All signals are PRD-001 compliant")
        elif has_signals:
            print(f"[WARN] SIGNALS: {signal_results['signals_invalid']} invalid signals found")
        else:
            print("[ERROR] SIGNALS: No signals found in Redis streams")

        if has_pnl:
            print("[OK] PNL: PnL data is being published")
        else:
            print("[ERROR] PNL: No PnL data found in Redis stream")

        if self.errors:
            print(f"\n[ERROR] ERRORS ({len(self.errors)}):")
            for error in self.errors:
                print(f"  {error}")

        if self.warnings:
            print(f"\n[WARN] WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings[:10]:  # Limit to first 10
                print(f"  {warning}")

        if has_signals and has_pnl and not self.errors:
            print("\n[OK] OVERALL: Bot is publishing PRD-compliant signals and PnL!")
        elif has_signals and not has_pnl:
            print("\n[WARN] OVERALL: Signals are being published but PnL is missing")
        elif not has_signals:
            print("\n[ERROR] OVERALL: Bot is not publishing signals. Check if bot is running.")

        await self.disconnect()


async def main():
    """Main entry point"""
    checker = PRDComplianceChecker()
    try:
        await checker.run_verification()
    except KeyboardInterrupt:
        print("\n\nVerification interrupted by user")
    except Exception as e:
        print(f"\n[ERROR] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

