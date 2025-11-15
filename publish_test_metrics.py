#!/usr/bin/env python
"""Test metrics publisher - publishes mock profitability metrics to Redis."""
import json
import redis
import ssl
import time
from datetime import datetime

# Connect to Redis
redis_client = redis.from_url(
    "rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
    decode_responses=True,
    ssl_cert_reqs=ssl.CERT_REQUIRED,
    ssl_ca_certs="config/certs/redis_ca.pem"
)

# Mock performance metrics (from backtesting results)
performance_metrics = {
    "monthly_roi_pct": 8.7,
    "profit_factor": 1.52,
    "sharpe_ratio": 1.41,
    "max_drawdown_pct": 8.3,
    "cagr_pct": 135.2,
    "win_rate_pct": 61.3,
    "total_trades": 742,
    "current_equity": 11245.50,
    "timestamp": datetime.utcnow().isoformat() + "Z"
}

# Mock regime data
regime_data = {
    "regime": "bull",
    "confidence": 0.82,
    "timestamp": datetime.utcnow().isoformat() + "Z"
}

# Publish to Redis
print("Publishing test metrics to Redis...")
redis_client.set(
    "bot:performance:current",
    json.dumps(performance_metrics),
    ex=3600  # 1 hour expiry
)
print(f"Published performance metrics: {json.dumps(performance_metrics, indent=2)}")

redis_client.set(
    "bot:regime:current",
    json.dumps(regime_data),
    ex=3600
)
print(f"Published regime data: {json.dumps(regime_data, indent=2)}")

redis_client.close()
print("\nDone! Metrics published successfully.")
print("\nTest the API endpoint:")
print("curl https://crypto-signals-api.fly.dev/metrics/profitability")
