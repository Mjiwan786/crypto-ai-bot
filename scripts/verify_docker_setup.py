#!/usr/bin/env python3
"""
Docker Setup Verification Script

Verifies that the Docker Compose setup is configured correctly for:
- Staging: PAPER mode, healthy, publishes to signals:staging
- Production: LIVE mode only with confirmation
- Logging: docker logs & ./logs
- Auto-restart: unless-stopped
"""

import os
import sys
import subprocess
import yaml
from pathlib import Path

def run_command(cmd, capture_output=True):
    """Run a command and return the result."""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def check_env_file(file_path, expected_vars):
    """Check if environment file has expected variables."""
    if not os.path.exists(file_path):
        return False, f"File {file_path} does not exist"
    
    with open(file_path, 'r') as f:
        content = f.read()
    
    missing_vars = []
    for var, expected_value in expected_vars.items():
        if f"{var}={expected_value}" not in content:
            missing_vars.append(f"{var}={expected_value}")
    
    if missing_vars:
        return False, f"Missing or incorrect variables: {missing_vars}"
    
    return True, "All variables found"

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
        'REDIS_URL': 'rediss://default:inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0'
    }
    
    success, message = check_env_file('.env.staging', staging_vars)
    if not success:
        return False, f"Staging environment file issue: {message}"
    
    # Check production environment file
    prod_vars = {
        'ENVIRONMENT': 'production',
        'PAPER_TRADING_ENABLED': 'false',
        'LIVE_TRADING_CONFIRMATION': 'I CONFIRM LIVE TRADING ENABLED',
        'REDIS_URL': 'rediss://default:inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818/0'
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
    print("🚀 Docker Setup Verification")
    print("=" * 50)
    
    checks = [
        ("Docker Compose Configuration", check_docker_compose_config),
        ("Environment Files", check_environment_files),
        ("Required Scripts", check_scripts),
        ("Docker Compose Syntax", check_docker_compose_syntax)
    ]
    
    all_passed = True
    
    for check_name, check_func in checks:
        print(f"\n📋 {check_name}")
        try:
            success, message = check_func()
            if success:
                print(f"✅ {message}")
            else:
                print(f"❌ {message}")
                all_passed = False
        except Exception as e:
            print(f"❌ Error during {check_name}: {e}")
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 All checks passed! Docker setup is ready.")
        print("\n📖 Usage:")
        print("  # Start staging (PAPER trading)")
        print("  docker-compose --profile staging up -d")
        print("\n  # Start production (LIVE trading)")
        print("  docker-compose --profile prod up -d")
        print("\n  # View logs")
        print("  docker-compose --profile staging logs -f bot")
        print("  docker-compose --profile prod logs -f bot-prod")
        return 0
    else:
        print("❌ Some checks failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())



