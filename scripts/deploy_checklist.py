#!/usr/bin/env python3
"""
Fly.io Deployment Checklist

Pre-deployment validation script to ensure all requirements are met
before deploying to Fly.io.

Usage:
    python scripts/deploy_checklist.py
    python scripts/deploy_checklist.py --skip-tests
"""

import asyncio
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

# Fix Windows console encoding
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class Colors:
    """Terminal colors"""

    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BLUE = "\033[94m"
    BOLD = "\033[1m"
    END = "\033[0m"


def print_header(text: str) -> None:
    """Print section header"""
    print(f"\n{Colors.BLUE}{Colors.BOLD}{'='*70}")
    print(f"  {text}")
    print(f"{'='*70}{Colors.END}\n")


def print_success(text: str) -> None:
    """Print success message"""
    print(f"{Colors.GREEN}✓{Colors.END} {text}")


def print_error(text: str) -> None:
    """Print error message"""
    print(f"{Colors.RED}✗{Colors.END} {text}")


def print_warning(text: str) -> None:
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠{Colors.END} {text}")


def check_fly_cli() -> Tuple[bool, str]:
    """Check if Fly.io CLI is installed"""
    try:
        result = subprocess.run(
            ["fly", "version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, "Fly CLI not responding"
    except FileNotFoundError:
        return False, "Fly CLI not installed"
    except Exception as e:
        return False, str(e)


def check_fly_auth() -> Tuple[bool, str]:
    """Check if authenticated with Fly.io"""
    try:
        result = subprocess.run(
            ["fly", "auth", "whoami"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            user = result.stdout.strip()
            return True, f"Logged in as: {user}"
        return False, "Not authenticated"
    except Exception as e:
        return False, str(e)


def check_docker() -> Tuple[bool, str]:
    """Check if Docker is installed and running"""
    try:
        result = subprocess.run(
            ["docker", "--version"], capture_output=True, text=True, timeout=5
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            return True, version
        return False, "Docker not responding"
    except FileNotFoundError:
        return False, "Docker not installed"
    except Exception as e:
        return False, str(e)


def check_dockerfile() -> Tuple[bool, str]:
    """Check if Dockerfile exists"""
    dockerfile = project_root / "Dockerfile"
    if dockerfile.exists():
        return True, "Dockerfile found"
    return False, "Dockerfile not found"


def check_fly_toml() -> Tuple[bool, str]:
    """Check if fly.toml exists and is valid"""
    fly_toml = project_root / "fly.toml"
    if not fly_toml.exists():
        return False, "fly.toml not found"

    # Basic validation
    try:
        content = fly_toml.read_text(encoding="utf-8")
    except Exception as e:
        return False, f"Cannot read fly.toml: {e}"

    if 'app = "crypto-ai-bot"' not in content:
        return False, "fly.toml missing app name"

    if "primary_region" not in content:
        return False, "fly.toml missing primary_region"

    return True, "fly.toml is valid"


def check_health_py() -> Tuple[bool, str]:
    """Check if health.py exists"""
    health_py = project_root / "health.py"
    if health_py.exists():
        return True, "health.py found"
    return False, "health.py not found"


def check_main_py() -> Tuple[bool, str]:
    """Check if main.py exists"""
    main_py = project_root / "main.py"
    if main_py.exists():
        return True, "main.py found"
    return False, "main.py not found"


def check_requirements() -> Tuple[bool, str]:
    """Check if requirements.txt exists"""
    requirements = project_root / "requirements.txt"
    if requirements.exists():
        lines = len(requirements.read_text().splitlines())
        return True, f"requirements.txt found ({lines} packages)"
    return False, "requirements.txt not found"


def check_redis_ca_cert() -> Tuple[bool, str]:
    """Check if Redis CA certificate exists"""
    ca_cert = project_root / "config" / "certs" / "redis_ca.pem"
    if ca_cert.exists():
        return True, "Redis CA certificate found"
    return False, "Redis CA certificate not found (config/certs/redis_ca.pem)"


def check_env_example() -> Tuple[bool, str]:
    """Check if .env.prod.example exists"""
    env_example = project_root / ".env.prod.example"
    if env_example.exists():
        return True, ".env.prod.example found"
    return False, ".env.prod.example not found"


async def run_preflight_tests() -> Tuple[bool, str]:
    """Run preflight tests"""
    try:
        # Import check scripts
        sys.path.insert(0, str(project_root / "scripts"))

        print("  Running Redis TLS check...")
        from check_redis_tls import main as redis_main

        redis_result = await redis_main()

        print("  Running Kraken API check...")
        from check_kraken_api import main as kraken_main

        kraken_result = await kraken_main()

        if redis_result == 0 and kraken_result == 0:
            return True, "All preflight tests passed"
        elif redis_result != 0:
            return False, "Redis TLS check failed"
        else:
            return False, "Kraken API check failed"

    except Exception as e:
        return False, f"Test error: {str(e)}"


def print_deployment_instructions():
    """Print deployment instructions"""
    print_header("Deployment Instructions")

    print(f"{Colors.BOLD}1. Set Fly.io Secrets:{Colors.END}")
    print("   fly secrets set \\")
    print('     REDIS_URL="rediss://default:PASSWORD@host:port/0" \\')
    print('     KRAKEN_API_KEY="your_api_key" \\')
    print('     KRAKEN_API_SECRET="your_api_secret" \\')
    print('     DISCORD_BOT_TOKEN="your_token"')
    print()

    print(f"{Colors.BOLD}2. Verify Secrets:{Colors.END}")
    print("   fly secrets list")
    print()

    print(f"{Colors.BOLD}3. Deploy Application:{Colors.END}")
    print("   fly deploy")
    print()

    print(f"{Colors.BOLD}4. Verify Deployment:{Colors.END}")
    print("   fly status")
    print("   fly logs")
    print("   fly ssh console -C 'curl http://localhost:8080/health'")
    print()

    print(f"{Colors.BOLD}5. Monitor Application:{Colors.END}")
    print("   fly logs -f")
    print("   fly dashboard")
    print()


async def main() -> int:
    """Main entry point"""
    skip_tests = "--skip-tests" in sys.argv

    print(f"\n{Colors.BOLD}Fly.io Deployment Checklist{Colors.END}")
    print(f"Timestamp: {datetime.utcnow().isoformat()}Z\n")

    checks = []

    # Infrastructure checks
    print_header("Infrastructure Requirements")

    check, msg = check_fly_cli()
    checks.append(("Fly.io CLI installed", check, msg))
    if check:
        print_success(f"Fly CLI: {msg}")
    else:
        print_error(f"Fly CLI: {msg}")
        print(
            "  Install: PowerShell: iwr https://fly.io/install.ps1 -useb | iex"
        )

    check, msg = check_fly_auth()
    checks.append(("Fly.io authenticated", check, msg))
    if check:
        print_success(f"Fly Auth: {msg}")
    else:
        print_error(f"Fly Auth: {msg}")
        print("  Run: fly auth login")

    check, msg = check_docker()
    # Docker is optional for deployment
    if check:
        print_success(f"Docker: {msg}")
    else:
        print_warning(f"Docker: {msg} (optional for local testing)")

    # File checks
    print_header("Required Files")

    file_checks = [
        ("Dockerfile", check_dockerfile),
        ("fly.toml", check_fly_toml),
        ("health.py", check_health_py),
        ("main.py", check_main_py),
        ("requirements.txt", check_requirements),
        ("Redis CA cert", check_redis_ca_cert),
        (".env.prod.example", check_env_example),
    ]

    for name, check_func in file_checks:
        check, msg = check_func()
        checks.append((name, check, msg))
        if check:
            print_success(f"{name}: {msg}")
        else:
            print_error(f"{name}: {msg}")

    # Preflight tests
    if not skip_tests:
        print_header("Preflight Tests")

        check, msg = await run_preflight_tests()
        checks.append(("Preflight tests", check, msg))
        if check:
            print_success(f"Tests: {msg}")
        else:
            print_error(f"Tests: {msg}")
    else:
        print_warning("Skipping preflight tests (--skip-tests)")

    # Summary
    print_header("Summary")

    total = len(checks)
    passed = sum(1 for _, check, _ in checks if check)
    failed = total - passed

    print(f"{'Check':<30} {'Status':<10} {'Details':<40}")
    print("-" * 80)

    for name, check, msg in checks:
        status = (
            f"{Colors.GREEN}PASS{Colors.END}"
            if check
            else f"{Colors.RED}FAIL{Colors.END}"
        )
        details = msg[:40]
        print(f"{name:<30} {status:<20} {details:<40}")

    print("-" * 80)
    print(
        f"\nTotal: {total} | "
        f"{Colors.GREEN}Passed: {passed}{Colors.END} | "
        f"{Colors.RED}Failed: {failed}{Colors.END}"
    )
    print()

    # Results
    # Count only critical failures (Docker is optional)
    critical_failures = sum(
        1
        for name, check, _ in checks
        if not check and name != "Docker installed"
    )

    if critical_failures == 0:
        print(f"{Colors.GREEN}{Colors.BOLD}✓ All critical checks passed!{Colors.END}")
        print(f"{Colors.GREEN}Ready for deployment.{Colors.END}\n")

        print_deployment_instructions()
        return 0
    else:
        print(
            f"{Colors.RED}{Colors.BOLD}✗ {critical_failures} critical check(s) failed!{Colors.END}"
        )
        print(f"{Colors.RED}Fix the issues above before deploying.{Colors.END}\n")
        return 1


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print(f"\n\n{Colors.YELLOW}Interrupted by user{Colors.END}")
        sys.exit(130)
    except Exception as e:
        print(f"\n{Colors.RED}Fatal error: {e}{Colors.END}")
        sys.exit(1)
