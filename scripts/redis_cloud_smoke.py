#!/usr/bin/env python3
"""
Redis Cloud TLS smoke test for crypto-ai-bot.

This script performs a comprehensive smoke test of the Redis Cloud TLS connection
utility, including connection, health checks, and basic operations.

Usage:
    python scripts/redis_cloud_smoke.py [--verbose] [--duration SECONDS]
"""

import asyncio
import argparse
import logging
import os
import sys
import time

from agents.infrastructure.redis_client import (
    RedisCloudClient,
    RedisCloudConfig,
    check_redis_cloud_health,
    create_data_pipeline_redis_client,
    create_kraken_ingestor_redis_client,
)

logger = logging.getLogger("redis_cloud_smoke")


async def test_basic_connection(config: RedisCloudConfig) -> bool:
    """Test basic Redis Cloud connection."""
    logger.info("Testing basic Redis Cloud connection...")
    
    try:
        async with RedisCloudClient(config) as client:
            # Test ping
            if not await client.ping():
                logger.error("❌ Ping failed")
                return False
            
            logger.info("✅ Basic connection successful")
            return True
            
    except Exception as e:
        logger.error(f"❌ Basic connection failed: {e}")
        return False


async def test_health_check(config: RedisCloudConfig) -> bool:
    """Test Redis Cloud health check."""
    logger.info("Testing Redis Cloud health check...")
    
    try:
        health_result = await check_redis_cloud_health(config)
        
        if not health_result.connected:
            logger.error(f"❌ Health check failed: {health_result.error_message}")
            return False
        
        logger.info(f"✅ Health check successful - Latency: {health_result.latency_ms:.2f}ms")
        logger.info(f"   Memory usage: {health_result.memory_usage_mb:.2f}MB ({health_result.memory_usage_percent:.1f}%)")
        logger.info(f"   Connections: {health_result.connection_count}")
        logger.info(f"   TLS active: {health_result.tls_active}")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Health check failed: {e}")
        return False


async def test_basic_operations(config: RedisCloudConfig) -> bool:
    """Test basic Redis operations."""
    logger.info("Testing basic Redis operations...")
    
    try:
        async with RedisCloudClient(config) as client:
            # Test set/get
            test_key = f"smoke_test:{int(time.time())}"
            test_value = "smoke_test_value"
            
            await client.set(test_key, test_value, ex=60)
            retrieved_value = await client.get(test_key)
            
            if retrieved_value != test_value:
                logger.error(f"❌ Set/Get test failed: expected '{test_value}', got '{retrieved_value}'")
                return False
            
            # Test delete
            await client.delete(test_key)
            deleted_value = await client.get(test_key)
            
            if deleted_value is not None:
                logger.error("❌ Delete test failed: key still exists")
                return False
            
            logger.info("✅ Basic operations successful")
            return True
            
    except Exception as e:
        logger.error(f"❌ Basic operations failed: {e}")
        return False


async def test_integration_helpers(config: RedisCloudConfig) -> bool:
    """Test integration helper functions."""
    logger.info("Testing integration helper functions...")
    
    try:
        # Test data pipeline helper
        data_pipeline_client = await create_data_pipeline_redis_client()
        if not await data_pipeline_client.ping():
            logger.error("❌ Data pipeline client ping failed")
            return False
        await data_pipeline_client.aclose()
        
        # Test kraken ingestor helper
        kraken_client = await create_kraken_ingestor_redis_client()
        if not await kraken_client.ping():
            logger.error("❌ Kraken ingestor client ping failed")
            return False
        await kraken_client.aclose()
        
        logger.info("✅ Integration helpers successful")
        return True
        
    except Exception as e:
        logger.error(f"❌ Integration helpers failed: {e}")
        return False


async def test_stream_operations(config: RedisCloudConfig) -> bool:
    """Test Redis Stream operations."""
    logger.info("Testing Redis Stream operations...")
    
    try:
        async with RedisCloudClient(config) as client:
            stream_name = f"smoke_test_stream:{int(time.time())}"
            test_data = {
                "test_field": "test_value",
                "timestamp": str(int(time.time())),
                "test_id": "smoke_test"
            }
            
            # Add entry to stream
            entry_id = await client.xadd(stream_name, test_data, maxlen=10, approximate=True)
            if not entry_id:
                logger.error("❌ Stream add failed")
                return False
            
            # Read from stream
            entries = await client.xread({stream_name: "0"}, count=1)
            if not entries or not entries[0][1]:
                logger.error("❌ Stream read failed")
                return False
            
            # Verify data
            stream_entries = entries[0][1]
            if len(stream_entries) != 1:
                logger.error(f"❌ Expected 1 stream entry, got {len(stream_entries)}")
                return False
            
            entry_data = stream_entries[0][1]
            if entry_data.get("test_field") != "test_value":
                logger.error(f"❌ Stream data mismatch: {entry_data}")
                return False
            
            # Cleanup
            await client.delete(stream_name)
            
            logger.info("✅ Stream operations successful")
            return True
            
    except Exception as e:
        logger.error(f"❌ Stream operations failed: {e}")
        return False


async def run_smoke_test(config: RedisCloudConfig, duration: int = 30) -> bool:
    """Run comprehensive smoke test."""
    logger.info("🚀 Starting Redis Cloud TLS smoke test...")
    logger.info(f"   Duration: {duration} seconds")
    logger.info(f"   Redis URL: {config.url}")
    logger.info(f"   CA Cert: {config.ca_cert_path or 'None'}")
    logger.info(f"   Client Cert: {config.client_cert_path or 'None'}")
    logger.info("")
    
    start_time = time.time()
    tests_passed = 0
    total_tests = 5
    
    # Test 1: Basic connection
    if await test_basic_connection(config):
        tests_passed += 1
    logger.info("")
    
    # Test 2: Health check
    if await test_health_check(config):
        tests_passed += 1
    logger.info("")
    
    # Test 3: Basic operations
    if await test_basic_operations(config):
        tests_passed += 1
    logger.info("")
    
    # Test 4: Integration helpers
    if await test_integration_helpers(config):
        tests_passed += 1
    logger.info("")
    
    # Test 5: Stream operations
    if await test_stream_operations(config):
        tests_passed += 1
    logger.info("")
    
    # Run continuous health checks for specified duration
    if duration > 0:
        logger.info(f"🔄 Running continuous health checks for {duration} seconds...")
        end_time = start_time + duration
        check_count = 0
        
        while time.time() < end_time:
            try:
                health_result = await check_redis_cloud_health(config)
                check_count += 1
                
                if health_result.connected:
                    logger.info(f"   Health check #{check_count}: ✅ Connected (latency: {health_result.latency_ms:.2f}ms)")
                else:
                    logger.warning(f"   Health check #{check_count}: ❌ Failed - {health_result.error_message}")
                
                await asyncio.sleep(5)  # Check every 5 seconds
                
            except Exception as e:
                logger.error(f"   Health check #{check_count}: ❌ Exception - {e}")
                await asyncio.sleep(5)
    
    # Summary
    elapsed_time = time.time() - start_time
    logger.info("=" * 60)
    logger.info(f"🎯 Smoke test completed in {elapsed_time:.2f} seconds")
    logger.info(f"   Tests passed: {tests_passed}/{total_tests}")
    
    if tests_passed == total_tests:
        logger.info("🎉 All tests passed! Redis Cloud TLS connection is working correctly.")
        return True
    else:
        logger.error(f"❌ {total_tests - tests_passed} test(s) failed. Check the logs above for details.")
        return False


def main():
    """Main function."""
    parser = argparse.ArgumentParser(description="Redis Cloud TLS smoke test")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    parser.add_argument("--duration", "-d", type=int, default=30, help="Duration for continuous health checks (seconds)")
    parser.add_argument("--url", help="Redis URL (overrides REDIS_URL env var)")
    parser.add_argument("--ca-cert", help="CA certificate path (overrides REDIS_CA_CERT env var)")
    parser.add_argument("--client-cert", help="Client certificate path (overrides REDIS_CLIENT_CERT env var)")
    parser.add_argument("--client-key", help="Client key path (overrides REDIS_CLIENT_KEY env var)")
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Create configuration
    config_kwargs = {}
    if args.url:
        config_kwargs["url"] = args.url
    if args.ca_cert:
        config_kwargs["ca_cert_path"] = args.ca_cert
    if args.client_cert:
        config_kwargs["client_cert_path"] = args.client_cert
    if args.client_key:
        config_kwargs["client_key_path"] = args.client_key
    
    try:
        config = RedisCloudConfig(**config_kwargs)
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        sys.exit(1)
    
    # Check required environment variables
    if not os.getenv("REDIS_URL") and not args.url:
        logger.error("❌ REDIS_URL environment variable not set. Use --url or set REDIS_URL.")
        sys.exit(1)
    
    # Run smoke test
    try:
        success = asyncio.run(run_smoke_test(config, args.duration))
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        logger.info("\n🛑 Smoke test interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Smoke test failed with exception: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

