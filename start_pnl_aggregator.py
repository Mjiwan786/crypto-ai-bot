#!/usr/bin/env python3
"""
Starter script for PnL Aggregator with Redis Cloud TLS support
"""
import os
import sys

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Set environment variables for PnL aggregator
os.environ["REDIS_URL"] = "rediss://default:&lt;REDIS_PASSWORD&gt;%2A%2A%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
os.environ["START_EQUITY"] = "10000.0"
os.environ["POLL_MS"] = "500"
os.environ["USE_PANDAS"] = "false"  # Disable pandas to avoid dependency issues

# Set Redis SSL certificate path
os.environ["REDIS_CA_CERT"] = r"C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem"

print("=" * 70)
print("Starting PnL Aggregator with Redis Cloud TLS")
print("=" * 70)
print(f"REDIS_URL: {os.environ['REDIS_URL'][:40]}...")
print(f"START_EQUITY: ${float(os.environ['START_EQUITY']):,.2f}")
print(f"POLL_MS: {os.environ['POLL_MS']}ms")
print(f"CA_CERT: {os.environ['REDIS_CA_CERT']}")
print("=" * 70)
print()

# Import and patch redis connection to use SSL cert
import redis

# Store original from_url function
original_from_url = redis.from_url

def patched_from_url(url, **kwargs):
    """Patched redis.from_url that adds SSL certificate support"""
    if url.startswith("rediss://"):
        # Add SSL certificate if not already provided
        if "ssl_ca_certs" not in kwargs:
            ca_cert_path = os.getenv("REDIS_CA_CERT")
            if ca_cert_path and os.path.exists(ca_cert_path):
                kwargs["ssl_ca_certs"] = ca_cert_path
                kwargs["ssl_cert_reqs"] = "required"
                print(f"🔒 Using SSL certificate: {ca_cert_path}")
    return original_from_url(url, **kwargs)

# Monkey patch redis.from_url
redis.from_url = patched_from_url

# Now import and run the aggregator
try:
    print("Importing PnL aggregator module...")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from monitoring.pnl_aggregator import run_pnl_aggregator

    print("Starting aggregator...\n")
    run_pnl_aggregator()

except KeyboardInterrupt:
    print("\n\n⏹️  Aggregator stopped by user")
    sys.exit(0)
except Exception as e:
    print(f"\n❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
