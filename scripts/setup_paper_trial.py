"""
scripts/setup_paper_trial.py - Paper Trial Setup Script

Interactive setup script for paper trading trial deployment.
Validates environment, creates config files, and tests connections.

Usage:
    python scripts/setup_paper_trial.py

Author: Crypto AI Bot Team
"""

import os
import sys
from pathlib import Path
import subprocess

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def print_header(text):
    """Print formatted header"""
    print("\n" + "=" * 80)
    print(text)
    print("=" * 80 + "\n")


def print_step(step, text):
    """Print formatted step"""
    print(f"\n{step}. {text}")
    print("-" * 80)


def check_conda_env():
    """Check if running in crypto-bot conda environment"""
    conda_env = os.getenv("CONDA_DEFAULT_ENV")
    if conda_env != "crypto-bot":
        print(f"❌ Not in crypto-bot conda environment (current: {conda_env})")
        print("   Run: conda activate crypto-bot")
        return False
    print("✅ Running in crypto-bot conda environment")
    return True


def check_redis_cert():
    """Check if Redis CA certificate exists"""
    ca_cert_path = project_root / "config" / "certs" / "redis_ca.pem"
    if not ca_cert_path.exists():
        print(f"❌ Redis CA certificate not found at: {ca_cert_path}")
        print("   Download from Redis Cloud dashboard")
        return False
    print(f"✅ Redis CA certificate found: {ca_cert_path}")
    return True


def check_redis_connection(redis_url, ca_cert_path):
    """Test Redis connection"""
    try:
        import redis

        # Parse connection parameters
        conn_params = {"decode_responses": True}

        # Add SSL/TLS
        if redis_url.startswith("rediss://"):
            conn_params["ssl"] = True
            if os.path.exists(ca_cert_path):
                conn_params["ssl_ca_certs"] = ca_cert_path
                conn_params["ssl_cert_reqs"] = "required"

        # Create client
        client = redis.from_url(redis_url, **conn_params)

        # Test connection
        client.ping()
        print("✅ Redis connection successful")
        return True

    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        return False


def create_env_file():
    """Create .env.paper from example"""
    env_example = project_root / ".env.paper.example"
    env_file = project_root / ".env.paper"

    if env_file.exists():
        overwrite = input(f".env.paper already exists. Overwrite? (y/n): ")
        if overwrite.lower() != 'y':
            print("Skipping .env.paper creation")
            return True

    # Copy example
    with open(env_example, 'r') as f:
        content = f.read()

    # Prompt for Redis URL
    redis_url = input("\nEnter Redis URL (rediss://...): ")
    if not redis_url:
        print("❌ Redis URL required")
        return False

    # Replace in content
    content = content.replace(
        "REDIS_URL=redis://default:YOUR_PASSWORD@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818",
        f"REDIS_URL={redis_url}"
    )

    # Write file
    with open(env_file, 'w') as f:
        f.write(content)

    print(f"✅ Created {env_file}")
    return True


def load_env_file():
    """Load .env.paper file"""
    env_file = project_root / ".env.paper"

    if not env_file.exists():
        print(f"❌ .env.paper not found at {env_file}")
        return False

    # Read and parse
    env_vars = {}
    with open(env_file, 'r') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env_vars[key.strip()] = value.strip()

    # Set environment variables
    for key, value in env_vars.items():
        os.environ[key] = value

    print(f"✅ Loaded environment from {env_file}")
    print(f"   Found {len(env_vars)} variables")
    return True


def check_dependencies():
    """Check if required Python packages are installed"""
    required = [
        "redis",
        "prometheus_client",
        "pandas",
        "numpy",
        "requests",
    ]

    print("\nChecking dependencies...")
    missing = []

    for package in required:
        try:
            __import__(package)
            print(f"  ✅ {package}")
        except ImportError:
            print(f"  ❌ {package}")
            missing.append(package)

    if missing:
        print(f"\n❌ Missing packages: {', '.join(missing)}")
        print("   Run: pip install " + " ".join(missing))
        return False

    print("✅ All dependencies installed")
    return True


def create_directories():
    """Create required directories"""
    dirs = [
        project_root / "logs",
        project_root / "reports",
        project_root / "config" / "certs",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        print(f"✅ Directory: {d}")

    return True


def main():
    """Main setup flow"""
    print_header("PAPER TRADING TRIAL - SETUP WIZARD")

    print("This wizard will help you set up the paper trading trial deployment.")
    print("It will validate your environment, create config files, and test connections.")

    # Step 1: Check conda environment
    print_step(1, "Check Conda Environment")
    if not check_conda_env():
        sys.exit(1)

    # Step 2: Check dependencies
    print_step(2, "Check Python Dependencies")
    if not check_dependencies():
        print("\nInstall missing dependencies and re-run setup")
        sys.exit(1)

    # Step 3: Create directories
    print_step(3, "Create Required Directories")
    create_directories()

    # Step 4: Check Redis certificate
    print_step(4, "Check Redis CA Certificate")
    if not check_redis_cert():
        print("\nDownload Redis CA certificate from Redis Cloud dashboard")
        print(f"Save to: {project_root / 'config' / 'certs' / 'redis_ca.pem'}")
        sys.exit(1)

    # Step 5: Create .env.paper
    print_step(5, "Create Environment Configuration")
    if not create_env_file():
        sys.exit(1)

    # Step 6: Load environment
    print_step(6, "Load Environment Variables")
    if not load_env_file():
        sys.exit(1)

    # Step 7: Test Redis connection
    print_step(7, "Test Redis Connection")
    redis_url = os.getenv("REDIS_URL")
    ca_cert_path = os.getenv("REDIS_CA_CERT")

    if not redis_url:
        print("❌ REDIS_URL not set in .env.paper")
        sys.exit(1)

    if not check_redis_connection(redis_url, ca_cert_path):
        print("\nFix Redis connection and re-run setup")
        sys.exit(1)

    # Step 8: Summary
    print_header("SETUP COMPLETE")

    print("✅ Environment: crypto-bot conda environment")
    print("✅ Dependencies: All installed")
    print("✅ Directories: Created")
    print("✅ Redis Certificate: Found")
    print("✅ Configuration: .env.paper created")
    print("✅ Redis Connection: Successful")

    print("\n" + "=" * 80)
    print("NEXT STEPS")
    print("=" * 80)
    print("\n1. Review configuration:")
    print("   cat .env.paper")

    print("\n2. Start paper trial:")
    print("   python scripts/run_paper_trial.py")

    print("\n3. Monitor in separate terminal:")
    print("   python scripts/monitor_paper_trial.py")

    print("\n4. Or deploy with Docker:")
    print("   docker-compose --profile paper up -d")

    print("\n5. Validate daily:")
    print("   python scripts/validate_paper_trading.py --from-redis")

    print("\n" + "=" * 80)
    print("For full instructions, see: PAPER_TRIAL_E2E_GUIDE.md")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
