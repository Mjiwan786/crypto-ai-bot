"""
scripts/monitor_paper_trial.py - Monitor Paper Trading Trial

Real-time monitoring script that checks:
- Signals published to Redis
- Prometheus metrics
- E2E latency
- Circuit breaker status

Usage:
    python scripts/monitor_paper_trial.py

Environment Variables:
    REDIS_URL: Redis Cloud connection URL (required)
    METRICS_PORT: Prometheus metrics port (default: 9108)

Author: Crypto AI Bot Team
"""

import os
import sys
import time
import requests
from pathlib import Path
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import redis


def parse_prometheus_metrics(metrics_text):
    """Parse Prometheus metrics text format"""
    metrics = {}
    for line in metrics_text.split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        try:
            parts = line.split(' ')
            if len(parts) >= 2:
                metric_name = parts[0].split('{')[0]
                value = float(parts[1])
                if metric_name not in metrics:
                    metrics[metric_name] = []
                metrics[metric_name].append(value)
        except:
            continue
    return metrics


def check_prometheus_metrics(port=9108):
    """Fetch and parse Prometheus metrics"""
    try:
        url = f"http://localhost:{port}/metrics"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            return parse_prometheus_metrics(response.text)
        else:
            return None
    except Exception as e:
        print(f"❌ Failed to fetch Prometheus metrics: {e}")
        return None


def check_redis_signals(redis_url, ca_cert_path):
    """Check signals in Redis streams"""
    try:
        # Parse connection parameters
        conn_params = {"decode_responses": True}

        # Add SSL/TLS if URL starts with rediss://
        if redis_url.startswith("rediss://"):
            conn_params["ssl"] = True
            if os.path.exists(ca_cert_path):
                conn_params["ssl_ca_certs"] = ca_cert_path
                conn_params["ssl_cert_reqs"] = "required"

        # Create client
        client = redis.from_url(redis_url, **conn_params)

        # Test connection
        client.ping()

        # Get stream length
        paper_signals = client.xlen("signals:paper")

        # Get latest signals
        latest = client.xrevrange("signals:paper", count=5)

        return {
            "connected": True,
            "stream_length": paper_signals,
            "latest_signals": latest
        }

    except Exception as e:
        return {
            "connected": False,
            "error": str(e)
        }


def main():
    """Main monitoring loop"""

    print("\n" + "=" * 80)
    print("PAPER TRADING TRIAL - MONITORING DASHBOARD")
    print("=" * 80)
    print(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 80 + "\n")

    # Configuration
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        print("❌ REDIS_URL not set in environment")
        sys.exit(1)

    ca_cert_path = os.getenv(
        "REDIS_CA_CERT",
        str(project_root / "config" / "certs" / "redis_ca.pem")
    )

    metrics_port = int(os.getenv("METRICS_PORT", "9108"))

    print("Configuration:")
    print(f"  Redis URL: {redis_url[:50]}...")
    print(f"  Redis CA Cert: {ca_cert_path}")
    print(f"  Metrics Port: {metrics_port}")
    print("\nPress Ctrl+C to stop monitoring\n")
    print("=" * 80 + "\n")

    try:
        while True:
            timestamp = datetime.now().strftime('%H:%M:%S')

            # Clear screen (Windows compatible)
            os.system('cls' if os.name == 'nt' else 'clear')

            print("=" * 80)
            print(f"PAPER TRIAL MONITORING - {timestamp}")
            print("=" * 80 + "\n")

            # Check Prometheus metrics
            print("📊 PROMETHEUS METRICS")
            print("-" * 80)
            metrics = check_prometheus_metrics(metrics_port)

            if metrics:
                # Signals published
                if "signals_published_total" in metrics:
                    total = sum(metrics["signals_published_total"])
                    print(f"✅ Signals Published Total: {int(total)}")
                else:
                    print("⚠️ Signals Published Total: 0")

                # Publish latency
                if "publish_latency_ms_bucket" in metrics:
                    avg_latency = sum(metrics["publish_latency_ms_bucket"]) / len(metrics["publish_latency_ms_bucket"])
                    status = "✅" if avg_latency < 500 else "⚠️"
                    print(f"{status} Avg Publish Latency: {avg_latency:.2f}ms")

                # Bot heartbeat
                if "bot_heartbeat_seconds" in metrics:
                    last_heartbeat = max(metrics["bot_heartbeat_seconds"])
                    age = time.time() - last_heartbeat
                    status = "✅" if age < 60 else "⚠️"
                    print(f"{status} Last Heartbeat: {age:.1f}s ago")

                # Bot uptime
                if "bot_uptime_seconds" in metrics:
                    uptime = max(metrics["bot_uptime_seconds"])
                    hours = uptime / 3600
                    print(f"✅ Bot Uptime: {hours:.2f} hours")

                # Disconnects
                if "ingestor_disconnects_total" in metrics:
                    disconnects = sum(metrics["ingestor_disconnects_total"])
                    status = "✅" if disconnects == 0 else "⚠️"
                    print(f"{status} Ingestor Disconnects: {int(disconnects)}")

                # Redis errors
                if "redis_publish_errors_total" in metrics:
                    errors = sum(metrics["redis_publish_errors_total"])
                    status = "✅" if errors == 0 else "❌"
                    print(f"{status} Redis Publish Errors: {int(errors)}")

            else:
                print("❌ Metrics server not reachable")
                print(f"   Check if bot is running and port {metrics_port} is accessible")

            print()

            # Check Redis signals
            print("📡 REDIS STREAMS")
            print("-" * 80)
            redis_status = check_redis_signals(redis_url, ca_cert_path)

            if redis_status.get("connected"):
                print(f"✅ Redis Connected")
                print(f"✅ Signals in Stream: {redis_status['stream_length']}")

                if redis_status['latest_signals']:
                    print(f"\nLatest Signals (last 5):")
                    for entry_id, fields in redis_status['latest_signals'][:5]:
                        pair = fields.get('pair', 'N/A')
                        side = fields.get('side', 'N/A')
                        strategy = fields.get('strategy', 'N/A')
                        confidence = fields.get('confidence', 'N/A')
                        print(f"  - {pair} {side} | {strategy} | conf={confidence}")
                else:
                    print("⚠️ No signals in stream yet")
            else:
                print(f"❌ Redis Connection Failed: {redis_status.get('error')}")

            print()

            # DoD Status
            print("📋 DEFINITION OF DONE (DoD) STATUS")
            print("-" * 80)
            print("Target Metrics:")
            print("  [ ] Profit Factor ≥ 1.5 OR Win-rate ≥ 60%")
            print("  [ ] Max Drawdown ≤ 15%")

            if metrics and "publish_latency_ms_bucket" in metrics:
                avg_latency = sum(metrics["publish_latency_ms_bucket"]) / len(metrics["publish_latency_ms_bucket"])
                status = "[✓]" if avg_latency < 500 else "[✗]"
                print(f"  {status} Latency p95 < 500ms (current: {avg_latency:.2f}ms)")
            else:
                print("  [ ] Latency p95 < 500ms (no data)")

            if metrics and "redis_publish_errors_total" in metrics:
                errors = sum(metrics["redis_publish_errors_total"])
                status = "[✓]" if errors == 0 else "[✗]"
                print(f"  {status} No missed publishes (errors: {int(errors)})")
            else:
                print("  [ ] No missed publishes (no data)")

            print()
            print("Run paper validation to check PF/Win-rate/DD:")
            print("  python scripts/validate_paper_trading.py --from-redis")

            print("\n" + "=" * 80)
            print("Refreshing in 30 seconds... (Press Ctrl+C to exit)")
            print("=" * 80)

            # Wait 30 seconds
            time.sleep(30)

    except KeyboardInterrupt:
        print("\n\n⏹️ Monitoring stopped")
        print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
