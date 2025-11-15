#!/usr/bin/env python3
"""
Test Staging Setup

Validates that the staging pipeline setup is correct before running.
"""

import json
import os
import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def test_environment_file():
    """Test that environment file exists and has required variables"""
    print("Testing environment file...")
    
    env_file = PROJECT_ROOT / ".env.staging"
    if not env_file.exists():
        print("❌ .env.staging not found")
        print("   Create it from env.staging.template")
        return False
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv(env_file)
    
    required_vars = [
        "ENVIRONMENT",
        "REDIS_URL",
        "TRADING_PAIRS"
    ]
    
    missing_vars = []
    for var in required_vars:
        if not os.getenv(var):
            missing_vars.append(var)
    
    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        return False
    
    if os.getenv("ENVIRONMENT") != "staging":
        print("❌ ENVIRONMENT must be 'staging'")
        return False
    
    print("✅ Environment file valid")
    return True


def test_process_manifests():
    """Test that process manifests exist and are valid JSON"""
    print("🔍 Testing process manifests...")
    
    manifest_files = [
        "procfiles/staging_ingestors.json",
        "procfiles/staging_strategies.json",
        "procfiles/staging_execution.json"
    ]
    
    for manifest_file in manifest_files:
        file_path = PROJECT_ROOT / manifest_file
        if not file_path.exists():
            print(f"❌ Manifest not found: {manifest_file}")
            return False
        
        try:
            with open(file_path) as f:
                data = json.load(f)
            
            if "procs" not in data:
                print(f"❌ Invalid manifest format: {manifest_file}")
                return False
            
            for proc in data["procs"]:
                required_fields = ["name", "cmd", "ready_regex", "log"]
                for field in required_fields:
                    if field not in proc:
                        print(f"❌ Missing field '{field}' in {manifest_file}")
                        return False
        
        except json.JSONDecodeError as e:
            print(f"❌ Invalid JSON in {manifest_file}: {e}")
            return False
    
    print("✅ Process manifests valid")
    return True


def test_runner_scripts():
    """Test that runner scripts exist"""
    print("🔍 Testing runner scripts...")
    
    runner_scripts = [
        "scripts/run_data_pipeline.py",
        "scripts/run_signal_analyst.py",
        "scripts/run_execution_agent.py"
    ]
    
    for script in runner_scripts:
        script_path = PROJECT_ROOT / script
        if not script_path.exists():
            print(f"❌ Runner script not found: {script}")
            return False
    
    print("✅ Runner scripts exist")
    return True


def test_configuration():
    """Test that configuration files exist"""
    print("🔍 Testing configuration...")
    
    config_files = [
        "config/overrides/staging.yaml",
        "config/merge_config.py"
    ]
    
    for config_file in config_files:
        file_path = PROJECT_ROOT / config_file
        if not file_path.exists():
            print(f"❌ Configuration file not found: {config_file}")
            return False
    
    print("✅ Configuration files exist")
    return True


def test_redis_connection():
    """Test Redis connection"""
    print("🔍 Testing Redis connection...")
    
    try:
        import redis
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        client = redis.from_url(redis_url, decode_responses=True)
        client.ping()
        print("✅ Redis connection successful")
        return True
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")
        print("   Make sure Redis is running and accessible")
        return False


def test_dependencies():
    """Test that required dependencies are available"""
    print("🔍 Testing dependencies...")
    
    required_packages = [
        "redis",
        "yaml",
        "dotenv",
        "aiohttp",
        "websockets"
    ]
    
    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"❌ Missing packages: {missing_packages}")
        print("   Install with: pip install " + " ".join(missing_packages))
        return False
    
    print("✅ Dependencies available")
    return True


def main():
    """Run all tests"""
    print("=" * 50)
    print("CRYPTO AI BOT - STAGING SETUP TEST")
    print("=" * 50)
    print()
    
    tests = [
        test_environment_file,
        test_process_manifests,
        test_runner_scripts,
        test_configuration,
        test_dependencies,
        test_redis_connection
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 50)
    if passed == total:
        print("✅ ALL TESTS PASSED - Staging pipeline ready!")
        print("   Run with: python scripts/run_staging.py --env .env.staging")
        return 0
    else:
        print(f"❌ {total - passed} TESTS FAILED - Fix issues before running")
        return 1


if __name__ == "__main__":
    sys.exit(main())
