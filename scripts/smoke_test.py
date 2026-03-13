#!/usr/bin/env python3
"""
Deploy Smoke Test — Sprint 2 Phase 4

Connects to Redis Cloud and verifies that all critical data streams
are populated with recent data. Designed to run post-deploy.

Usage:
    python scripts/smoke_test.py          # reads REDIS_URL from env or .env
    REDIS_URL=rediss://... python scripts/smoke_test.py

Exit codes:
    0 — all critical checks pass
    1 — one or more critical checks failed
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Ensure project root on sys.path
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _load_env() -> None:
    """Load .env file if present."""
    for env_file in [".env", ".env.prod", ".env.local"]:
        env_path = Path(_project_root) / env_file
        if env_path.exists():
            try:
                from dotenv import load_dotenv
                load_dotenv(env_path)
                return
            except ImportError:
                # Manual parse
                with open(env_path) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, _, val = line.partition("=")
                            val = val.strip().strip('"').strip("'")
                            os.environ.setdefault(key.strip(), val)
                return


def main() -> int:
    _load_env()

    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        print("ERROR: REDIS_URL not set. Set it in env or .env file.")
        return 1

    ca_cert = os.getenv("REDIS_CA_CERT", "")
    if not ca_cert:
        ca_cert_path = Path(_project_root) / "config" / "certs" / "redis_ca.pem"
        if ca_cert_path.exists():
            ca_cert = str(ca_cert_path)

    # Connect to Redis
    try:
        import redis as sync_redis
    except ImportError:
        print("ERROR: redis package not installed. Run: pip install redis")
        return 1

    conn_params: dict = {
        "socket_connect_timeout": 10,
        "decode_responses": True,
    }
    if redis_url.startswith("rediss://") and ca_cert:
        conn_params["ssl_ca_certs"] = ca_cert
        conn_params["ssl_cert_reqs"] = "required"

    try:
        r = sync_redis.from_url(redis_url, **conn_params)
        r.ping()
    except Exception as e:
        print(f"ERROR: Cannot connect to Redis: {e}")
        return 1

    print("=" * 65)
    print("  DEPLOY SMOKE TEST — AI Predicted Signals")
    print("=" * 65)
    print()

    now = time.time()
    results: list[dict] = []
    any_critical_fail = False

    # ── Check 1: signals:paper:BTC-USD ──────────────────────────────
    check = {"name": "signals:paper:BTC-USD", "critical": True}
    try:
        entries = r.xrevrange("signals:paper:BTC-USD", count=1)
        if entries:
            msg_id, fields = entries[0]
            # Parse timestamp from message ID (milliseconds)
            ts_ms = int(msg_id.split("-")[0])
            age_s = now - (ts_ms / 1000)
            check["status"] = "PASS" if age_s < 300 else "WARN"
            check["detail"] = f"1 entry, age={age_s:.0f}s"
            if age_s >= 300:
                check["detail"] += " (>5min, may be stale)"
        else:
            check["status"] = "FAIL"
            check["detail"] = "No entries"
            any_critical_fail = True
    except Exception as e:
        check["status"] = "FAIL"
        check["detail"] = str(e)[:60]
        any_critical_fail = True
    results.append(check)

    # ── Check 2: kraken:ohlc:1:BTC-USD ─────────────────────────────
    # Try multiple key formats (legacy uses :1:, newer uses :1m:)
    check = {"name": "kraken:ohlc:*:BTC-USD", "critical": True}
    found_ohlc = False
    ohlc_detail = ""
    for key_pattern in ["kraken:ohlc:1:BTC-USD", "kraken:ohlc:1m:BTC-USD"]:
        try:
            entries = r.xrevrange(key_pattern, count=1)
            if entries:
                msg_id, fields = entries[0]
                ts_ms = int(msg_id.split("-")[0])
                age_s = now - (ts_ms / 1000)
                found_ohlc = True
                ohlc_detail = f"{key_pattern}: 1 entry, age={age_s:.0f}s"
                break
        except Exception:
            continue

    if found_ohlc:
        check["status"] = "PASS"
        check["detail"] = ohlc_detail
    else:
        # Try scanning for any kraken:ohlc key
        try:
            keys = list(r.scan_iter("kraken:ohlc:*:BTC*", count=10))
            if keys:
                check["status"] = "WARN"
                check["detail"] = f"Found keys: {', '.join(keys[:3])}"
            else:
                check["status"] = "FAIL"
                check["detail"] = "No OHLCV keys found"
                any_critical_fail = True
        except Exception as e:
            check["status"] = "FAIL"
            check["detail"] = str(e)[:60]
            any_critical_fail = True
    results.append(check)

    # ── Check 3: kraken:heartbeat ───────────────────────────────────
    check = {"name": "kraken:heartbeat", "critical": True}
    try:
        entries = r.xrevrange("kraken:heartbeat", count=1)
        if entries:
            msg_id, fields = entries[0]
            ts_ms = int(msg_id.split("-")[0])
            age_s = now - (ts_ms / 1000)
            if age_s < 60:
                check["status"] = "PASS"
                check["detail"] = f"age={age_s:.0f}s (< 60s)"
            else:
                check["status"] = "WARN"
                check["detail"] = f"age={age_s:.0f}s (> 60s, engine may be restarting)"
        else:
            # Try STRING key format
            hb = r.get("kraken:heartbeat")
            if hb:
                check["status"] = "PASS"
                check["detail"] = f"STRING key exists: {str(hb)[:40]}"
            else:
                check["status"] = "FAIL"
                check["detail"] = "No heartbeat found"
                any_critical_fail = True
    except Exception as e:
        check["status"] = "FAIL"
        check["detail"] = str(e)[:60]
        any_critical_fail = True
    results.append(check)

    # ── Check 4: mcp:market_context ─────────────────────────────────
    check = {"name": "mcp:market_context", "critical": False}
    try:
        ctx = r.get("mcp:market_context")
        if ctx:
            data = json.loads(ctx)
            regime = data.get("regime", "unknown")
            check["status"] = "PASS"
            check["detail"] = f"regime={regime}"
        else:
            check["status"] = "WARN"
            check["detail"] = "Key missing (regime writer may not have run yet)"
    except json.JSONDecodeError:
        check["status"] = "WARN"
        check["detail"] = "Key exists but invalid JSON"
    except Exception as e:
        check["status"] = "WARN"
        check["detail"] = str(e)[:60]
    results.append(check)

    # ── Check 5: pnl:paper:summary ──────────────────────────────────
    check = {"name": "pnl:paper:summary", "critical": False}
    try:
        summary = r.get("pnl:paper:summary")
        if summary:
            data = json.loads(summary)
            equity = data.get("equity", "?")
            check["status"] = "PASS"
            check["detail"] = f"equity=${equity}"
        else:
            check["status"] = "WARN"
            check["detail"] = "Key missing (ok if no trades yet)"
    except Exception as e:
        check["status"] = "WARN"
        check["detail"] = str(e)[:60]
    results.append(check)

    # ── Check 6: pnl:paper:equity_curve ─────────────────────────────
    check = {"name": "pnl:paper:equity_curve", "critical": False}
    try:
        length = r.xlen("pnl:paper:equity_curve")
        if length > 0:
            check["status"] = "PASS"
            check["detail"] = f"{length} entries"
        else:
            check["status"] = "WARN"
            check["detail"] = "Empty (ok if no trades yet)"
    except Exception as e:
        check["status"] = "WARN"
        check["detail"] = str(e)[:60]
    results.append(check)

    # ── Print results table ─────────────────────────────────────────
    print(f"  {'Check':<35} {'Status':<8} {'Detail'}")
    print(f"  {'-'*35} {'-'*8} {'-'*40}")
    for res in results:
        status = res["status"]
        icon = {"PASS": "+", "FAIL": "X", "WARN": "!"}[status]
        crit = " *" if res.get("critical") else "  "
        print(f"  [{icon}]{crit}{res['name']:<33} {status:<8} {res.get('detail', '')}")

    print()
    print("  * = critical check (causes exit code 1 on FAIL)")
    print()

    # ── Summary ─────────────────────────────────────────────────────
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_warn = sum(1 for r in results if r["status"] == "WARN")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")

    if any_critical_fail:
        print(f"  RESULT: FAIL ({n_pass} pass, {n_warn} warn, {n_fail} fail)")
        print("=" * 65)
        return 1
    else:
        print(f"  RESULT: PASS ({n_pass} pass, {n_warn} warn, {n_fail} fail)")
        print("=" * 65)
        return 0


if __name__ == "__main__":
    sys.exit(main())
