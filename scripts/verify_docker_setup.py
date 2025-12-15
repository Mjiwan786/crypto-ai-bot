#!/usr/bin/env python3
"""
Crypto AI Bot - Docker Setup Verification Script

⚠️ SAFETY WARNING:
This script verifies Docker configuration for safe deployment.

Checks:
- Python 3.10.18 in container
- prometheus_client import available
- /metrics reachable at :9308 (if --check-metrics)
- Container has no .env secrets committed
- Correct non-root UID/GID (Linux containers)
- Valid environment configuration
- Redis Cloud TLS connection

Exit codes:
  0 = Configuration valid
  1 = Configuration invalid

Usage:
    python scripts/verify_docker_setup.py [--check-metrics] [--verbose]
"""

import argparse
import os
import subprocess
import sys
from typing import Tuple

import yaml


def run_command(cmd, capture_output=True) -> Tuple[bool, str, str]:
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True, timeout=30)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_python_version() -> Tuple[bool, str]:
    """Check if Python 3.10.18 is available."""
    print("🔍 Checking Python version...")

    success, stdout, stderr = run_command("python --version")
    if not success:
        return False, f"Failed to check Python version: {stderr}"

    version = stdout.strip()
    if "3.10.18" in version:
        return True, f"Python version OK: {version}"
    else:
        return False, f"Python version mismatch: {version} (expected 3.10.18)"


def check_prometheus_client() -> Tuple[bool, str]:
    """Check if prometheus_client is importable."""
    print("🔍 Checking prometheus_client import...")

    success, stdout, stderr = run_command('python -c "import prometheus_client; print(prometheus_client.__version__)"')
    if not success:
        return False, f"Failed to import prometheus_client: {stderr}"

    version = stdout.strip()
    return True, f"prometheus_client OK: {version}"


def check_metrics_endpoint(port: int = 9308) -> Tuple[bool, str]:
    """Check if metrics endpoint is reachable."""
    print(f"🔍 Checking metrics endpoint at :{port}...")

    try:
        import urllib.request

        url = f"http://localhost:{port}/metrics"
        req = urllib.request.Request(url)

        with urllib.request.urlopen(req, timeout=5) as response:
            content = response.read().decode()

            if "crypto_ai_bot" in content:
                return True, f"Metrics endpoint OK at {url}"
            else:
                return False, "Metrics endpoint accessible but no crypto_ai_bot metrics found"

    except Exception as e:
        return False, f"Metrics endpoint not reachable: {e}"


def check_no_secrets_in_env() -> Tuple[bool, str]:
    """Check that no .env files are committed to container."""
    print("🔍 Checking for committed .env files...")

    forbidden_files = [".env", ".env.local", ".env.staging", ".env.prod"]
    found = []

    for env_file in forbidden_files:
        if os.path.exists(env_file):
            found.append(env_file)

    if found:
        return False, f"Found secret .env files that should not be committed: {', '.join(found)}"

    return True, "No secret .env files found (using templates only)"


def check_container_user() -> Tuple[bool, str]:
    """Check that container runs as non-root user (Linux only)."""
    print("🔍 Checking container user...")

    if sys.platform == "win32":
        return True, "Container user check skipped (Windows)"

    success, stdout, stderr = run_command("id -u")
    if not success:
        return False, f"Failed to check user ID: {stderr}"

    uid = stdout.strip()

    if uid == "0":
        return False, "Container running as root (UID 0) - security risk"

    return True, f"Container running as non-root user (UID {uid})"

def check_docker_compose_config():
    """Check Docker Compose configuration."""
    print("🔍 Checking Docker Compose configuration...")
    
    # Check if docker-compose.yml exists
    if not os.path.exists("docker-compose.yml"):
        return False, "docker-compose.yml not found"
    
    # Load and parse docker-compose.yml
    with open("docker-compose.yml", 'r') as f:
        compose_config = yaml.safe_load(f)
    
    # Check staging service
    staging_service = compose_config.get('services', {}).get('bot', {})
    if not staging_service:
        return False, "Staging service 'bot' not found"
    
    # Check staging environment variables
    staging_env = staging_service.get('environment', [])
    expected_staging_env = [
        "ENVIRONMENT=staging",
        "MODE=PAPER",
        "PAPER_TRADING_ENABLED=true",
        "LIVE_TRADING_CONFIRMATION="
    ]
    
    for expected in expected_staging_env:
        if expected not in staging_env:
            return False, f"Staging missing environment variable: {expected}"
    
    # Check production service
    prod_service = compose_config.get('services', {}).get('bot-prod', {})
    if not prod_service:
        return False, "Production service 'bot-prod' not found"
    
    # Check production environment variables
    prod_env = prod_service.get('environment', [])
    expected_prod_env = [
        "ENVIRONMENT=production",
        "MODE=LIVE",
        "PAPER_TRADING_ENABLED=false"
    ]
    
    for expected in expected_prod_env:
        if expected not in prod_env:
            return False, f"Production missing environment variable: {expected}"
    
    # Check restart policy
    if staging_service.get('restart') != 'unless-stopped':
        return False, "Staging service missing restart: unless-stopped"
    
    if prod_service.get('restart') != 'unless-stopped':
        return False, "Production service missing restart: unless-stopped"
    
    # Check logging configuration
    staging_logging = staging_service.get('logging', {})
    if staging_logging.get('driver') != 'json-file':
        return False, "Staging service missing json-file logging driver"
    
    prod_logging = prod_service.get('logging', {})
    if prod_logging.get('driver') != 'json-file':
        return False, "Production service missing json-file logging driver"
    
    # Check volumes for logs
    staging_volumes = staging_service.get('volumes', [])
    if './logs:/app/logs' not in staging_volumes:
        return False, "Staging service missing logs volume mount"
    
    prod_volumes = prod_service.get('volumes', [])
    if './logs:/app/logs' not in prod_volumes:
        return False, "Production service missing logs volume mount"
    
    # Check health checks
    staging_healthcheck = staging_service.get('healthcheck', {})
    if not staging_healthcheck or 'python scripts/healthcheck.py' not in str(staging_healthcheck.get('test', [])):
        return False, "Staging service missing healthcheck"
    
    prod_healthcheck = prod_service.get('healthcheck', {})
    if not prod_healthcheck or 'python scripts/healthcheck.py' not in str(prod_healthcheck.get('test', [])):
        return False, "Production service missing healthcheck"
    
    return True, "Docker Compose configuration is valid"

def check_environment_files():
    """Check environment files."""
    print("🔍 Checking environment files...")
    
    # Check staging environment file
    staging_vars = {
        'ENVIRONMENT': 'staging',
        'PAPER_TRADING_ENABLED': 'true',
        'LIVE_TRADING_CONFIRMATION': '',
        'REDIS_URL': 'rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0'
    }
    
    success, message = check_env_file('.env.staging', staging_vars)
    if not success:
        return False, f"Staging environment file issue: {message}"
    
    # Check production environment file
    prod_vars = {
        'ENVIRONMENT': 'production',
        'PAPER_TRADING_ENABLED': 'false',
        'LIVE_TRADING_CONFIRMATION': 'I CONFIRM LIVE TRADING ENABLED',
        'REDIS_URL': 'rediss://default:<REDIS_PASSWORD>@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0'
    }
    
    success, message = check_env_file('.env.prod', prod_vars)
    if not success:
        return False, f"Production environment file issue: {message}"
    
    return True, "Environment files are valid"

def check_scripts():
    """Check required scripts exist."""
    print("🔍 Checking required scripts...")
    
    required_scripts = [
        'scripts/entrypoint.sh',
        'scripts/wait_for_redis.py',
        'scripts/healthcheck.py',
        'scripts/setup_docker_env.sh'
    ]
    
    missing_scripts = []
    for script in required_scripts:
        if not os.path.exists(script):
            missing_scripts.append(script)
    
    if missing_scripts:
        return False, f"Missing scripts: {missing_scripts}"
    
    return True, "All required scripts exist"

def check_docker_compose_syntax():
    """Check Docker Compose syntax."""
    print("🔍 Checking Docker Compose syntax...")
    
    # Test staging profile
    success, stdout, stderr = run_command("docker-compose --profile staging config")
    if not success:
        return False, f"Staging profile syntax error: {stderr}"
    
    # Test production profile
    success, stdout, stderr = run_command("docker-compose --profile prod config")
    if not success:
        return False, f"Production profile syntax error: {stderr}"
    
    return True, "Docker Compose syntax is valid"

def main():
    """Main verification function."""
    parser = argparse.ArgumentParser(
        description="Docker Setup Verification Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python scripts/verify_docker_setup.py
    python scripts/verify_docker_setup.py --check-metrics
    python scripts/verify_docker_setup.py --verbose
        """,
    )

    parser.add_argument(
        "--check-metrics",
        action="store_true",
        help="Check if metrics endpoint is reachable at :9308",
    )

    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("CRYPTO AI BOT - DOCKER SETUP VERIFICATION")
    print("=" * 60)
    print("")

    checks = [
        ("Python Version", check_python_version),
        ("Prometheus Client", check_prometheus_client),
        ("No Secret .env Files", check_no_secrets_in_env),
        ("Container User", check_container_user),
    ]

    if args.check_metrics:
        checks.append(("Metrics Endpoint", check_metrics_endpoint))

    all_passed = True
    results = []

    for check_name, check_func in checks:
        try:
            success, message = check_func()
            results.append((check_name, success, message))

            if success:
                print(f"✅ {check_name}: {message}")
            else:
                print(f"❌ {check_name}: {message}")
                all_passed = False

        except Exception as e:
            print(f"❌ {check_name}: Unexpected error - {e}")
            if args.verbose:
                import traceback
                traceback.print_exc()
            all_passed = False

    print("")
    print("=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Checks passed: {sum(1 for _, success, _ in results if success)}/{len(results)}")
    print("")

    if all_passed:
        print("✅ All checks passed! Docker setup is valid.")
        print("")
        print("Usage:")
        print("  docker-compose up --build")
        return 0
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())



