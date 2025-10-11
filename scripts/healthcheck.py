#!/usr/bin/env python3
"""
Health check script for crypto_ai_bot.

Loads .env, verifies environment variables, tests Redis PING,
loads config with merge_config.load_config, checks strategy allocations,
and prints mode + selected signals stream.

Exit 0 if healthy, 1 otherwise. Runtime <2s.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
from urllib.parse import urlparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from dotenv import load_dotenv
    from config.merge_config import load_config
except ImportError as e:
    print(f"ERROR: Missing required dependency: {e}", file=sys.stderr)
    print("Install with: pip install redis python-dotenv pyyaml", file=sys.stderr)
    sys.exit(1)


def load_environment(env_path: Optional[str] = None) -> None:
    """Load environment variables from .env file."""
    if env_path:
        env_file = Path(env_path)
    else:
        # Try common .env locations
        env_locations = [
            Path(".env"),
            Path("config/.env"),
            Path("../.env"),
        ]
        
        env_file = None
        for location in env_locations:
            if location.exists():
                env_file = location
                break
    
    if env_file and env_file.exists():
        load_dotenv(env_file)
        print(f"Loaded environment from: {env_file}")
    else:
        print("No .env file found, using system environment variables")


def verify_environment_variables() -> bool:
    """Verify required environment variables are set."""
    required_vars = {
        'ENVIRONMENT': 'Environment name (staging, production, etc.)',
        'REDIS_URL': 'Redis connection URL',
        'KRAKEN_API_URL': 'Kraken API URL'
    }
    
    missing_vars = []
    for var, description in required_vars.items():
        if not os.getenv(var):
            missing_vars.append(f"{var} ({description})")
    
    if missing_vars:
        print(f"ERROR: Missing required environment variables:")
        for var in missing_vars:
            print(f"  - {var}")
        return False
    
    print("✅ Environment variables verified")
    return True


def test_redis_connection() -> bool:
    """Test Redis connection with PING."""
    redis_url = os.getenv('REDIS_URL')
    if not redis_url:
        print("ERROR: REDIS_URL not set")
        return False
    
    try:
        # Parse Redis URL
        parsed = urlparse(redis_url)
        ssl = parsed.scheme == 'rediss'
        
        conn_params = {
            'host': parsed.hostname or 'localhost',
            'port': parsed.port or (6380 if ssl else 6379),
            'password': parsed.password,
            'ssl': ssl,
            'ssl_cert_reqs': None,  # Don't verify SSL certificates
        }
        
        # Handle database number from path
        if parsed.path and len(parsed.path) > 1:
            try:
                conn_params['db'] = int(parsed.path[1:])
            except ValueError:
                pass
        
        # Remove None values
        conn_params = {k: v for k, v in conn_params.items() if v is not None}
        
        # Test connection
        r = redis.Redis(**conn_params)
        response = r.ping()
        
        if response:
            print("✅ Redis connection successful")
            return True
        else:
            print("ERROR: Redis PING returned False")
            return False
            
    except Exception as e:
        print(f"ERROR: Redis connection failed: {e}")
        return False


def load_and_validate_config() -> Optional[Dict[str, Any]]:
    """Load configuration and validate strategy allocations."""
    environment = os.getenv('ENVIRONMENT', 'staging')
    
    try:
        config = load_config(environment)
        print(f"✅ Configuration loaded for environment: {environment}")
        
        # Check strategy allocations
        if 'strategies' in config and 'allocations' in config['strategies']:
            allocations = config['strategies']['allocations']
            total_allocation = sum(allocations.values())
            
            print(f"Strategy allocations: {allocations}")
            print(f"Total allocation: {total_allocation:.3f}")
            
            # Check if allocations sum to approximately 1.0 ± 0.05
            if abs(total_allocation - 1.0) <= 0.05:
                print("✅ Strategy allocations valid (≈1.0 ±0.05)")
            else:
                print(f"ERROR: Strategy allocations sum to {total_allocation:.3f}, expected ≈1.0 ±0.05")
                return None
        else:
            print("WARNING: No strategy allocations found in config")
        
        return config
        
    except Exception as e:
        print(f"ERROR: Failed to load configuration: {e}")
        return None


def print_mode_and_signals(config: Dict[str, Any]) -> None:
    """Print mode and selected signals stream."""
    # Print mode
    mode = config.get('mode', 'UNKNOWN')
    print(f"Mode: {mode}")
    
    # Print signals stream
    signals_stream = None
    
    # Try different possible locations for signals stream config
    if 'redis' in config and 'streams' in config['redis']:
        streams = config['redis']['streams']
        if 'active_signals' in streams:
            signals_stream = streams['active_signals']
        elif 'signals_paper' in streams:
            signals_stream = streams['signals_paper']
        elif 'signals_live' in streams:
            signals_stream = streams['signals_live']
    
    # Fallback to default streams config
    if not signals_stream:
        try:
            from config.stream_registry import get_stream
            signals_stream = get_stream('signals')
        except:
            # Last resort - check if we can find it in the streams.yaml
            try:
                import yaml
                streams_config_path = Path("config/streams.yaml")
                if streams_config_path.exists():
                    with open(streams_config_path, 'r') as f:
                        streams_data = yaml.safe_load(f)
                        if 'subscribe' in streams_data and 'signals' in streams_data['subscribe']:
                            signals_stream = streams_data['subscribe']['signals']
            except:
                pass
    
    if signals_stream:
        print(f"Selected signals stream: {signals_stream}")
        
        # Validate that staging uses signals:staging
        environment = os.getenv('ENVIRONMENT', 'staging')
        if environment == 'staging' and 'staging' not in signals_stream:
            print(f"WARNING: Staging environment should use signals:staging, got {signals_stream}")
        elif environment == 'production' and 'live' not in signals_stream and 'prod' not in signals_stream:
            print(f"WARNING: Production environment should use signals:live or signals:prod, got {signals_stream}")
    else:
        print("WARNING: Could not determine signals stream")


def main():
    """Main health check function."""
    parser = argparse.ArgumentParser(description="Health check for crypto AI bot")
    parser.add_argument(
        "--env-path",
        help="Path to .env file (default: auto-detect)"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=2,
        help="Maximum runtime in seconds (default: 2)"
    )
    
    args = parser.parse_args()
    
    start_time = time.time()
    
    print("🔍 Starting health check...")
    
    # Load environment
    load_environment(args.env_path)
    
    # Verify environment variables
    if not verify_environment_variables():
        sys.exit(1)
    
    # Test Redis connection
    if not test_redis_connection():
        sys.exit(1)
    
    # Load and validate configuration
    config = load_and_validate_config()
    if config is None:
        sys.exit(1)
    
    # Print mode and signals stream
    print_mode_and_signals(config)
    
    # Check runtime
    runtime = time.time() - start_time
    print(f"Health check completed in {runtime:.2f}s")
    
    if runtime > args.timeout:
        print(f"WARNING: Health check took {runtime:.2f}s, exceeding timeout of {args.timeout}s")
    
    print("✅ All health checks passed")
    sys.exit(0)


if __name__ == "__main__":
    main()
