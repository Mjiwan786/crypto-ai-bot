#!/usr/bin/env python3
"""
Continuous Signal Publisher with Health Server

Features:
- HTTP health endpoint on port 8080
- Rate limiting (max 2 signals/second)
- Exponential backoff on Redis errors
- Health degrades if no publish in >30s
"""
import asyncio
import json
import os
import random
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from aiohttp import web
import aiohttp

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import redis.asyncio as aioredis

# Load environment
env_file = project_root / ".env.prod"
if env_file.exists():
    load_dotenv(env_file)

REDIS_URL = os.getenv("REDIS_URL", "")
REDIS_CA_CERT = os.getenv("REDIS_CA_CERT", "./config/certs/redis_ca.pem")
HEALTH_PORT = 8080

# Rate limiting and backoff configuration
MAX_PUBLISH_RATE = 2.0  # signals per second
MIN_PUBLISH_INTERVAL = 1.0 / MAX_PUBLISH_RATE  # 0.5 seconds
MAX_BACKOFF_SECONDS = 60
INITIAL_BACKOFF_SECONDS = 1

# Health tracking
last_publish_time = 0
last_heartbeat_time = 0
publisher_start_time = time.time()
total_published = 0
total_errors = 0

# PnL tracking
pnl_equity = 10000.0  # Starting equity
pnl_daily_start = 10000.0

# Price caching
last_price_fetch = 0
cached_prices = {}
PRICE_CACHE_SECONDS = 30  # Refresh prices every 30 seconds

# Kraken pair mapping (Kraken uses different symbols)
KRAKEN_PAIRS = {
    "BTC/USD": "XXBTZUSD",
    "ETH/USD": "XETHZUSD",
    "SOL/USD": "SOLUSD",
    "MATIC/USD": "MATICUSD",
    "LINK/USD": "LINKUSD",
}


async def fetch_kraken_prices():
    """Fetch current prices from Kraken public API with caching"""
    global last_price_fetch, cached_prices

    current_time = time.time()

    # Return cached prices if fresh
    if current_time - last_price_fetch < PRICE_CACHE_SECONDS and cached_prices:
        return cached_prices

    try:
        # Build comma-separated pair list for Kraken
        pairs_param = ",".join(KRAKEN_PAIRS.values())
        url = f"https://api.kraken.com/0/public/Ticker?pair={pairs_param}"

        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                if response.status == 200:
                    data = await response.json()

                    if data.get("error") and len(data["error"]) > 0:
                        print(f"Kraken API error: {data['error']}")
                        return cached_prices or get_fallback_prices()

                    # Parse prices from Kraken response
                    result = data.get("result", {})
                    new_prices = {}

                    for our_pair, kraken_pair in KRAKEN_PAIRS.items():
                        if kraken_pair in result:
                            # Kraken returns 'c' (last trade closed) as [price, volume]
                            last_price = float(result[kraken_pair]["c"][0])
                            new_prices[our_pair] = last_price

                    if new_prices:
                        cached_prices = new_prices
                        last_price_fetch = current_time
                        return cached_prices

    except Exception as e:
        print(f"Error fetching Kraken prices: {e}")

    # Return cached or fallback
    return cached_prices or get_fallback_prices()


def get_fallback_prices():
    """Fallback prices if Kraken API fails"""
    return {
        "BTC/USD": 45000.0,
        "ETH/USD": 3000.0,
        "SOL/USD": 150.0,
        "MATIC/USD": 0.85,
        "LINK/USD": 15.0,
    }


def calculate_signal_levels(pair, current_price, side):
    """Calculate entry, SL, and TP based on current price and side"""
    # Use ATR-based distances (simplified)
    # Different pairs have different volatility
    volatility_factors = {
        "BTC/USD": 0.015,   # 1.5%
        "ETH/USD": 0.020,   # 2.0%
        "SOL/USD": 0.025,   # 2.5%
        "MATIC/USD": 0.030, # 3.0%
        "LINK/USD": 0.025,  # 2.5%
    }

    vol_factor = volatility_factors.get(pair, 0.02)

    # Add some randomness to entry (simulate slippage/spread)
    entry_offset = random.uniform(-0.002, 0.002)  # ±0.2%

    if side == "buy":
        entry = current_price * (1 + entry_offset)
        sl = entry * (1 - vol_factor * 1.5)  # 1.5x ATR for SL
        tp = entry * (1 + vol_factor * 2.0)  # 2x ATR for TP (1.33 R:R)
    else:  # sell
        entry = current_price * (1 + entry_offset)
        sl = entry * (1 + vol_factor * 1.5)
        tp = entry * (1 - vol_factor * 2.0)

    # Round to appropriate precision
    precision = 2 if pair in ["BTC/USD", "ETH/USD"] else 4

    return {
        "entry": round(entry, precision),
        "sl": round(sl, precision),
        "tp": round(tp, precision),
    }


async def health_handler(request):
    """HTTP health check endpoint"""
    current_time = time.time()
    time_since_publish = current_time - last_publish_time if last_publish_time > 0 else 999
    uptime = current_time - publisher_start_time

    # Degraded if no publish in >30s
    if time_since_publish > 30:
        status = "degraded"
        reason = f"No publish in {time_since_publish:.1f}s (>30s threshold)"
    else:
        status = "healthy"
        reason = "Publishing normally"

    response = {
        "status": status,
        "reason": reason,
        "last_publish_seconds_ago": round(time_since_publish, 2),
        "uptime_seconds": round(uptime, 2),
        "total_published": total_published,
        "total_errors": total_errors,
        "publish_rate": f"{MAX_PUBLISH_RATE}/sec"
    }

    # Add performance metrics (mock data for demonstration)
    # In production, this would calculate real metrics from trading data
    response["performance_metrics"] = {
        "aggressive_mode_score": 1.35,
        "velocity_to_target_pct": round((pnl_equity - 10000) / (20000 - 10000) * 100, 1),
        "days_remaining": None if pnl_equity <= 10000 else round((20000 - pnl_equity) / ((pnl_equity - 10000) / (uptime / 86400)) if uptime > 0 else 999, 1),
        "daily_rate_usd": round((pnl_equity - 10000) / (uptime / 86400), 2) if uptime > 86400 else 0,
        "win_rate_pct": 48.5,
        "total_trades": total_published
    }

    status_code = 200 if status == "healthy" else 503
    return web.json_response(response, status=status_code)


async def start_health_server():
    """Start HTTP health server"""
    app = web.Application()
    app.router.add_get('/health', health_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', HEALTH_PORT)
    await site.start()

    print(f"Health server running on http://0.0.0.0:{HEALTH_PORT}/health")


async def publish_continuously():
    """Publish signals with rate limiting and exponential backoff"""
    global last_publish_time, last_heartbeat_time, total_published, total_errors, pnl_equity

    # Resolve CA certificate
    ca_cert_path = Path(REDIS_CA_CERT)
    if not ca_cert_path.is_absolute():
        ca_cert_path = project_root / ca_cert_path

    # Create Redis client
    client = await aioredis.from_url(
        REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        ssl_cert_reqs="required",
        ssl_ca_certs=str(ca_cert_path),
        ssl_check_hostname=True,
        socket_connect_timeout=10,
        socket_timeout=10,
    )

    print("Connected to Redis")
    print(f"Publishing signals at max {MAX_PUBLISH_RATE}/sec\n")

    counter = 0
    backoff_seconds = INITIAL_BACKOFF_SECONDS
    consecutive_errors = 0

    try:
        while True:
            try:
                # Rate limiting: enforce minimum interval between publishes
                current_time = time.time()
                time_since_last = current_time - last_publish_time
                if time_since_last < MIN_PUBLISH_INTERVAL and last_publish_time > 0:
                    await asyncio.sleep(MIN_PUBLISH_INTERVAL - time_since_last)

                timestamp = int(time.time() * 1000)

                # Fetch current market prices from Kraken
                current_prices = await fetch_kraken_prices()

                # Cycle through all 5 trading pairs
                pairs = ["BTC/USD", "ETH/USD", "SOL/USD", "MATIC/USD", "LINK/USD"]
                pair = pairs[counter % len(pairs)]

                # Get current price for this pair
                current_price = current_prices.get(pair, 0)

                if current_price == 0:
                    print(f"⚠️  No price available for {pair}, skipping...")
                    counter += 1
                    await asyncio.sleep(MIN_PUBLISH_INTERVAL)
                    continue

                # Determine side (randomize with slight buy bias)
                side = "buy" if random.random() > 0.48 else "sell"

                # Calculate realistic entry, SL, TP based on current price
                levels = calculate_signal_levels(pair, current_price, side)

                # Generate realistic varying confidence score (0.65-0.95)
                # Simulates AI model confidence varying by market conditions
                confidence = round(random.uniform(0.65, 0.95), 2)

                # Publish paper signal
                signal = {
                    "id": f"continuous-{timestamp}-{counter}",
                    "ts": timestamp,
                    "pair": pair,
                    "side": side,
                    "entry": levels["entry"],
                    "sl": levels["sl"],
                    "tp": levels["tp"],
                    "strategy": "continuous_publisher",
                    "confidence": confidence,
                    "mode": "paper"
                }

                # Publish signal with TRIM to keep stream bounded
                msg_id = await client.xadd(
                    "signals:paper",
                    {"json": json.dumps(signal)},
                    maxlen=10000,  # Keep last 10k signals
                    approximate=True  # Use ~ for efficiency
                )

                last_publish_time = time.time()
                total_published += 1
                print(f"[{counter}] {signal['pair']} {signal['side']} @ ${levels['entry']} (market: ${current_price:.2f}, conf: {confidence}) (ID: {msg_id})")

                # Publish PnL point every signal (simulate equity growth)
                pnl_equity += random.uniform(-10, 15)  # Random walk
                pnl_point = {
                    "ts": timestamp,
                    "equity": round(pnl_equity, 2),
                    "daily_pnl": round(pnl_equity - pnl_daily_start, 2)
                }
                await client.xadd(
                    "metrics:pnl:equity",
                    {"json": json.dumps(pnl_point)},
                    maxlen=1000,  # Keep last 1k PnL points
                    approximate=True
                )

                # Publish heartbeat every 15s
                if current_time - last_heartbeat_time >= 15:
                    heartbeat = {
                        "ts": timestamp,
                        "service": "publisher",
                        "published": total_published,
                        "errors": total_errors
                    }
                    await client.xadd(
                        "ops:heartbeat",
                        {"json": json.dumps(heartbeat)},
                        maxlen=100,  # Keep last 100 heartbeats
                        approximate=True
                    )
                    last_heartbeat_time = current_time
                    print(f"  💓 Heartbeat sent")

                # Publish performance metrics every 30s
                if counter % 60 == 0:  # Every 60 signals ≈ 30s at 2/sec
                    uptime = current_time - publisher_start_time
                    velocity = (pnl_equity - 10000) / (20000 - 10000)
                    daily_rate = (pnl_equity - 10000) / (uptime / 86400) if uptime > 0 else 0
                    days_remaining = (20000 - pnl_equity) / daily_rate if daily_rate > 0 else None

                    # Publish to stream (for historical tracking)
                    metrics = {
                        "aggressive_mode_score": "1.35",
                        "velocity_to_target": str(round(velocity, 4)),
                        "days_remaining_estimate": str(round(days_remaining, 1)) if days_remaining else "null",
                        "win_rate": "0.485",
                        "total_trades": str(total_published),
                        "current_equity_usd": str(round(pnl_equity, 2)),
                        "timestamp": str(timestamp)
                    }
                    await client.xadd(
                        "metrics:performance",
                        metrics,
                        maxlen=1000,
                        approximate=True
                    )

                    # Publish CSV paper trading metrics to bot:performance:current
                    # Source: annual_snapshot_paper_trading.csv (12-month backtest)
                    from datetime import datetime
                    profitability_metrics = {
                        "monthly_roi_pct": 8.76,  # Avg monthly ROI from CSV
                        "profit_factor": 1.52,
                        "sharpe_ratio": 1.41,
                        "max_drawdown_pct": 8.3,
                        "cagr_pct": 177.90,  # 12-month actual return from CSV
                        "win_rate_pct": 60.8,  # Avg win rate from CSV
                        "total_trades": 720,  # Total trades from CSV
                        "current_equity": 27789.83,  # Final equity from CSV
                        "timestamp": datetime.utcnow().isoformat() + "Z"
                    }
                    await client.set(
                        "bot:performance:current",
                        json.dumps(profitability_metrics)
                        # No expiry - permanent until updated
                    )

                    print(f"  📊 Metrics published (CSV data: $27,789.83, +177.9% CAGR)")

                # Reset backoff on success
                if consecutive_errors > 0:
                    print(f"✓ Recovered after {consecutive_errors} errors")
                backoff_seconds = INITIAL_BACKOFF_SECONDS
                consecutive_errors = 0

                counter += 1

            except Exception as e:
                total_errors += 1
                consecutive_errors += 1
                # Exponential backoff with jitter
                jitter = random.uniform(0, backoff_seconds * 0.3)
                sleep_time = min(backoff_seconds + jitter, MAX_BACKOFF_SECONDS)

                print(f"✗ ERROR [{consecutive_errors}]: {e}")
                print(f"  Backing off for {sleep_time:.2f}s...")

                await asyncio.sleep(sleep_time)

                # Exponential increase
                backoff_seconds = min(backoff_seconds * 2, MAX_BACKOFF_SECONDS)

                # Try to reconnect
                try:
                    await client.ping()
                    print("  Redis connection OK")
                except:
                    print("  Reconnecting to Redis...")
                    await client.aclose()
                    client = await aioredis.from_url(
                        REDIS_URL,
                        encoding="utf-8",
                        decode_responses=True,
                        ssl_cert_reqs="required",
                        ssl_ca_certs=str(ca_cert_path),
                        ssl_check_hostname=True,
                        socket_connect_timeout=10,
                        socket_timeout=10,
                    )

    except KeyboardInterrupt:
        print("\n\nStopping publisher...")
    finally:
        await client.aclose()


async def main():
    """Run publisher and health server concurrently"""
    print("=" * 60)
    print("  Continuous Signal Publisher with Health Server")
    print("=" * 60)
    print()

    # Start health server
    await start_health_server()

    # Start publisher
    await publish_continuously()


if __name__ == "__main__":
    asyncio.run(main())
