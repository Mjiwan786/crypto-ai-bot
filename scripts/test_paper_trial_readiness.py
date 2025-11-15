"""
scripts/test_paper_trial_readiness.py - Paper Trial Readiness Test

Comprehensive readiness check before deploying paper trading trial.
Validates all components, configurations, and connections.

Usage:
    python scripts/test_paper_trial_readiness.py

Author: Crypto AI Bot Team
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_section(title):
    """Print section header"""
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def test_conda_env():
    """Test 1: Conda environment"""
    print("\n[1/10] Testing conda environment...")
    conda_env = os.getenv("CONDA_DEFAULT_ENV")
    if conda_env == "crypto-bot":
        print("✅ Running in crypto-bot conda environment")
        return True
    else:
        print(f"❌ Not in crypto-bot environment (current: {conda_env})")
        print("   Run: conda activate crypto-bot")
        return False


def test_dependencies():
    """Test 2: Python dependencies"""
    print("\n[2/10] Testing Python dependencies...")
    required = {
        "redis": "Redis client",
        "prometheus_client": "Prometheus metrics",
        "pandas": "Data analysis",
        "numpy": "Numerical operations",
        "requests": "HTTP client",
        "pydantic": "Data validation",
    }

    all_ok = True
    for package, desc in required.items():
        try:
            __import__(package)
            print(f"  ✅ {package} ({desc})")
        except ImportError:
            print(f"  ❌ {package} ({desc}) - NOT INSTALLED")
            all_ok = False

    if all_ok:
        print("✅ All dependencies installed")
    else:
        print("❌ Missing dependencies - run: pip install redis prometheus_client pandas numpy requests pydantic")

    return all_ok


def test_files():
    """Test 3: Required files exist"""
    print("\n[3/10] Testing required files...")
    required_files = [
        "scripts/run_paper_trial.py",
        "scripts/monitor_paper_trial.py",
        "scripts/validate_paper_trading.py",
        "scripts/setup_paper_trial.py",
        "monitoring/metrics_exporter.py",
        "streams/publisher.py",
        "models/signal_dto.py",
        "engine/__init__.py",
        "docker-compose.yml",
        ".env.paper.example",
        "PAPER_TRIAL_E2E_GUIDE.md",
    ]

    all_ok = True
    for file_path in required_files:
        full_path = project_root / file_path
        if full_path.exists():
            print(f"  ✅ {file_path}")
        else:
            print(f"  ❌ {file_path} - NOT FOUND")
            all_ok = False

    if all_ok:
        print("✅ All required files present")
    else:
        print("❌ Missing files")

    return all_ok


def test_redis_cert():
    """Test 4: Redis CA certificate"""
    print("\n[4/10] Testing Redis CA certificate...")
    ca_cert_path = project_root / "config" / "certs" / "redis_ca.pem"

    if ca_cert_path.exists():
        print(f"  ✅ Redis CA cert found: {ca_cert_path}")
        return True
    else:
        print(f"  ❌ Redis CA cert not found: {ca_cert_path}")
        print("     Download from Redis Cloud dashboard")
        return False


def test_env_file():
    """Test 5: Environment file"""
    print("\n[5/10] Testing environment configuration...")
    env_file = project_root / ".env.paper"

    if env_file.exists():
        print(f"  ✅ .env.paper found")

        # Parse env file
        with open(env_file, 'r') as f:
            content = f.read()
            if "YOUR_PASSWORD" in content:
                print("  ⚠️ .env.paper contains placeholder values")
                print("     Update REDIS_URL with actual credentials")
                return False

        return True
    else:
        print(f"  ❌ .env.paper not found")
        print("     Run: python scripts/setup_paper_trial.py")
        return False


def test_redis_connection():
    """Test 6: Redis connection"""
    print("\n[6/10] Testing Redis connection...")

    # Load env
    env_file = project_root / ".env.paper"
    if not env_file.exists():
        print("  ⚠️ Skipping (no .env.paper)")
        return True

    # Parse env
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()

    redis_url = env_vars.get("REDIS_URL")
    ca_cert_path = env_vars.get("REDIS_CA_CERT")

    if not redis_url:
        print("  ⚠️ REDIS_URL not set in .env.paper")
        return False

    try:
        import redis

        # Parse connection parameters
        conn_params = {"decode_responses": True}

        # Add SSL/TLS
        if redis_url.startswith("rediss://"):
            conn_params["ssl"] = True
            if ca_cert_path and os.path.exists(ca_cert_path):
                conn_params["ssl_ca_certs"] = ca_cert_path
                conn_params["ssl_cert_reqs"] = "required"

        # Create client
        client = redis.from_url(redis_url, **conn_params)

        # Test connection
        client.ping()
        print(f"  ✅ Redis connection successful")

        # Check streams
        paper_len = client.xlen("signals:paper")
        print(f"  ✅ signals:paper stream length: {paper_len}")

        return True

    except Exception as e:
        print(f"  ❌ Redis connection failed: {e}")
        return False


def test_signal_dto():
    """Test 7: Signal DTO"""
    print("\n[7/10] Testing SignalDTO...")

    try:
        from models.signal_dto import create_signal_dto

        signal = create_signal_dto(
            ts_ms=1730000000000,
            pair="BTC-USD",
            side="long",
            entry=50000.0,
            sl=49000.0,
            tp=52000.0,
            strategy="test_strategy",
            confidence=0.75,
            mode="paper"
        )

        # Verify fields
        assert signal.strategy == "test_strategy", "strategy field missing"
        assert signal.confidence == 0.75, "confidence field missing"
        assert signal.entry == 50000.0, "entry field missing"
        assert signal.sl == 49000.0, "sl field missing"
        assert signal.tp == 52000.0, "tp field missing"

        # Calculate RR
        risk = signal.entry - signal.sl
        reward = signal.tp - signal.entry
        rr = reward / risk

        print(f"  ✅ SignalDTO created successfully")
        print(f"  ✅ Fields: strategy={signal.strategy}, confidence={signal.confidence}")
        print(f"  ✅ Prices: entry={signal.entry}, sl={signal.sl}, tp={signal.tp}")
        print(f"  ✅ Risk/Reward: {rr:.2f}:1")

        return True

    except Exception as e:
        print(f"  ❌ SignalDTO test failed: {e}")
        return False


def test_metrics_exporter():
    """Test 8: Metrics exporter"""
    print("\n[8/10] Testing Prometheus metrics exporter...")

    try:
        from monitoring.metrics_exporter import (
            signals_published_total,
            publish_latency_ms,
            bot_heartbeat_seconds,
            bot_uptime_seconds,
            stream_lag_seconds,
        )

        print("  ✅ signals_published_total counter")
        print("  ✅ publish_latency_ms histogram")
        print("  ✅ bot_heartbeat_seconds gauge")
        print("  ✅ bot_uptime_seconds gauge")
        print("  ✅ stream_lag_seconds gauge")
        print("✅ Metrics exporter ready")

        return True

    except Exception as e:
        print(f"  ❌ Metrics exporter test failed: {e}")
        return False


def test_publisher():
    """Test 9: Signal publisher"""
    print("\n[9/10] Testing signal publisher...")

    try:
        from streams.publisher import SignalPublisher, PublisherConfig

        # Create config (don't connect)
        config = PublisherConfig(
            redis_url="redis://localhost:6379",
            max_retries=3,
        )

        publisher = SignalPublisher(config=config)

        print("  ✅ SignalPublisher imported")
        print("  ✅ PublisherConfig created")
        print("✅ Signal publisher ready")

        return True

    except Exception as e:
        print(f"  ❌ Signal publisher test failed: {e}")
        return False


def test_docker_compose():
    """Test 10: Docker compose configuration"""
    print("\n[10/10] Testing Docker Compose configuration...")

    docker_compose = project_root / "docker-compose.yml"

    if not docker_compose.exists():
        print("  ❌ docker-compose.yml not found")
        return False

    with open(docker_compose, 'r') as f:
        content = f.read()

        # Check for paper-bot service
        if "paper-bot:" in content:
            print("  ✅ paper-bot service defined")
        else:
            print("  ❌ paper-bot service not found")
            return False

        # Check for profile
        if "profile:" in content or "profiles:" in content:
            print("  ✅ Docker profile configured")
        else:
            print("  ⚠️ Docker profile not found")

        # Check for metrics port
        if "9108:9108" in content or "9108" in content:
            print("  ✅ Metrics port exposed (9108)")
        else:
            print("  ⚠️ Metrics port not exposed")

    print("✅ Docker Compose ready")
    return True


def main():
    """Run all tests"""
    print_section("PAPER TRADING TRIAL - READINESS CHECK")

    print("\nThis script validates that all components are ready for deployment.")
    print("If any test fails, follow the instructions to fix the issue.\n")

    # Run all tests
    results = []
    results.append(("Conda Environment", test_conda_env()))
    results.append(("Python Dependencies", test_dependencies()))
    results.append(("Required Files", test_files()))
    results.append(("Redis CA Certificate", test_redis_cert()))
    results.append(("Environment File", test_env_file()))
    results.append(("Redis Connection", test_redis_connection()))
    results.append(("SignalDTO", test_signal_dto()))
    results.append(("Metrics Exporter", test_metrics_exporter()))
    results.append(("Signal Publisher", test_publisher()))
    results.append(("Docker Compose", test_docker_compose()))

    # Print summary
    print_section("READINESS CHECK SUMMARY")

    passed = 0
    failed = 0

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {name}")
        if result:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {passed}/{len(results)} passed")

    # Final verdict
    print_section("VERDICT")

    if failed == 0:
        print("✅ ALL CHECKS PASSED - READY FOR DEPLOYMENT")
        print("\nNext steps:")
        print("1. Deploy paper trial:")
        print("   python scripts/run_paper_trial.py")
        print("\n2. Monitor in separate terminal:")
        print("   python scripts/monitor_paper_trial.py")
        print("\n3. See full guide:")
        print("   cat PAPER_TRIAL_E2E_GUIDE.md")
        return 0
    else:
        print(f"❌ {failed} CHECKS FAILED - NOT READY")
        print("\nFix the failed checks and re-run this script:")
        print("   python scripts/test_paper_trial_readiness.py")
        return 1


if __name__ == "__main__":
    sys.exit(main())
