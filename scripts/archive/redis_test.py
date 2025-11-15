#!/usr/bin/env python3
"""
Redis SSL Connection Test Script
Tests your specific Redis Cloud configuration
"""

import json
import ssl
import time

import redis


def test_redis_connection():
    """Test Redis Cloud SSL connection with your credentials"""
    
    # Your Redis Cloud URL
    REDIS_URL = "rediss://default:Salam78614**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
    
    print("🔗 Testing Redis Cloud SSL connection...")
    print("=" * 50)
    
    try:
        # Create SSL context for Redis Cloud
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        # Connect to Redis Cloud
        r = redis.from_url(
            REDIS_URL,
            ssl_cert_reqs=None,
            ssl_ca_certs=None,
            ssl_check_hostname=False,
            decode_responses=True,
            socket_connect_timeout=10,
            socket_keepalive=True,
            health_check_interval=30
        )
        
        # Test basic connection
        print("1. Testing basic connection...")
        ping_result = r.ping()
        print(f"   ✅ Ping successful: {ping_result}")
        
        # Test read/write operations
        print("\n2. Testing read/write operations...")
        test_key = "test:backtest_setup"
        test_value = "connection_successful"
        
        r.setex(test_key, 60, test_value)
        retrieved_value = r.get(test_key)
        
        if retrieved_value == test_value:
            print("   ✅ Read/Write operations successful")
        else:
            print(f"   ❌ Read/Write failed: expected '{test_value}', got '{retrieved_value}'")
            return False
        
        # Clean up test key
        r.delete(test_key)
        
        # Test JSON operations (used by backtest system)
        print("\n3. Testing JSON operations...")
        json_test_key = "test:json_data"
        json_test_data = {
            "market_regime": {"trend": "bull", "confidence": 0.85},
            "strategy_signals": ["trend_following", "breakout"],
            "timestamp": time.time()
        }
        
        r.setex(json_test_key, 60, json.dumps(json_test_data))
        retrieved_json = r.get(json_test_key)
        
        if retrieved_json:
            parsed_data = json.loads(retrieved_json)
            if parsed_data["market_regime"]["trend"] == "bull":
                print("   ✅ JSON operations successful")
            else:
                print("   ❌ JSON parsing failed")
                return False
        
        # Clean up
        r.delete(json_test_key)
        
        # Test namespace operations (backtest pattern)
        print("\n4. Testing namespace operations...")
        namespace = "crypto_bot_backtest"
        
        test_data = {
            f"{namespace}:regime:BTC/USD": {"trend": "bull", "volatility": "medium"},
            f"{namespace}:signal:momentum": {"confidence": 0.8, "side": "buy"},
            f"{namespace}:performance": {"total_return": 15.5, "sharpe": 1.2}
        }
        
        # Store test data
        for key, value in test_data.items():
            r.setex(key, 300, json.dumps(value))  # 5 minute expiry
        
        # Retrieve and verify
        for key, expected_value in test_data.items():
            retrieved = r.get(key)
            if retrieved:
                parsed = json.loads(retrieved)
                print(f"   ✅ {key.split(':')[-1]}: stored and retrieved")
            else:
                print(f"   ❌ {key}: failed to retrieve")
                return False
        
        # Clean up namespace test data
        for key in test_data.keys():
            r.delete(key)
        
        # Get Redis info
        print("\n5. Redis instance information...")
        info = r.info()
        print(f"   📊 Redis version: {info.get('redis_version', 'unknown')}")
        print(f"   💾 Memory used: {info.get('used_memory_human', 'unknown')}")
        print(f"   🔗 Connected clients: {info.get('connected_clients', 'unknown')}")
        print(f"   ⏱️  Uptime: {info.get('uptime_in_seconds', 0)} seconds")
        
        print("\n🎉 All tests passed! Your Redis Cloud setup is ready for backtesting.")
        return True
        
    except redis.ConnectionError as e:
        print(f"❌ Redis connection failed: {e}")
        print("Troubleshooting:")
        print("1. Check if your Redis Cloud instance is running")
        print("2. Verify the URL and credentials are correct")
        print("3. Ensure your IP is whitelisted in Redis Cloud")
        return False
        
    except redis.AuthenticationError as e:
        print(f"❌ Redis authentication failed: {e}")
        print("Check your username and password in the Redis URL")
        return False
        
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False

def test_backtest_context_operations():
    """Test specific operations used by the backtest system"""
    
    REDIS_URL = "rediss://default:Salam78614**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
    
    print("\n🧪 Testing backtest-specific context operations...")
    print("=" * 50)
    
    try:
        ssl_context = ssl.create_default_context()
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE
        
        r = redis.from_url(
            REDIS_URL, 
            ssl_cert_reqs=None,
            ssl_ca_certs=None,
            ssl_check_hostname=False,
            decode_responses=True
        )
        
        namespace = "backtest"
        
        # Simulate market regime storage
        regime_data = {
            "trend": "bull",
            "volatility": "medium", 
            "confidence": 0.82,
            "indicators": {
                "rsi": 65.5,
                "atr_pct": 0.025,
                "sma_ratio": 1.05
            }
        }
        
        regime_key = f"{namespace}:regime:BTC/USD:2024-08-15T12:00:00"
        r.setex(regime_key, 3600, json.dumps(regime_data))
        print("✅ Market regime data stored")
        
        # Simulate signal storage
        signal_data = {
            "strategy": "trend_following",
            "side": "buy",
            "confidence": 0.85,
            "size": 500.0
        }
        
        signal_key = f"{namespace}:signal:2024-08-15T12:05:00:BTC/USD:trend_following"
        r.setex(signal_key, 3600, json.dumps(signal_data))
        print("✅ Trading signal data stored")
        
        # Simulate performance tracking
        performance_data = {
            "total_return": 18.5,
            "sharpe_ratio": 1.35,
            "max_drawdown": -6.2,
            "win_rate": 68.5,
            "total_trades": 42
        }
        
        perf_key = f"{namespace}:final_results"
        r.setex(perf_key, 86400, json.dumps(performance_data))  # 24 hour expiry
        print("✅ Performance data stored")
        
        # Test retrieval
        retrieved_regime = json.loads(r.get(regime_key))
        retrieved_signal = json.loads(r.get(signal_key))
        retrieved_perf = json.loads(r.get(perf_key))
        
        print(f"✅ Retrieved regime: {retrieved_regime['trend']} market")
        print(f"✅ Retrieved signal: {retrieved_signal['strategy']} {retrieved_signal['side']}")
        print(f"✅ Retrieved performance: {retrieved_perf['total_return']}% return")
        
        # Test pattern matching (used for getting all signals)
        pattern = f"{namespace}:signal:*"
        matching_keys = r.keys(pattern)
        print(f"✅ Pattern matching found {len(matching_keys)} signal keys")
        
        # Cleanup
        for key in [regime_key, signal_key, perf_key]:
            r.delete(key)
        
        print("🎉 Backtest context operations successful!")
        return True
        
    except Exception as e:
        print(f"❌ Backtest context test failed: {e}")
        return False

if __name__ == "__main__":
    print("🚀 Redis Cloud Connection Test for Crypto Trading Bot")
    print("=" * 60)
    
    # Test basic connection
    basic_success = test_redis_connection()
    
    if basic_success:
        # Test backtest-specific operations
        context_success = test_backtest_context_operations()
        
        if context_success:
            print("\n🎉 SUCCESS: Your Redis Cloud setup is fully ready!")
            print("=" * 60)
            print("Next steps:")
            print("1. Run: python3 scripts/comprehensive_agent_backtest.py --redis-url 'rediss://...' --start 1000 --days 30")
            print("2. Check results in: reports/comprehensive_backtest/")
            print("3. Monitor Redis Cloud dashboard for real-time usage")
        else:
            print("\n⚠️  Basic connection works, but backtest operations failed")
    else:
        print("\n❌ Redis connection failed. Please fix connection issues first.")
    
    print("\n" + "=" * 60)