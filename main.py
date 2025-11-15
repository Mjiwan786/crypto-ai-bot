#!/usr/bin/env python3
"""
Crypto AI Bot - Main Entry Point

A production-ready crypto trading system with multi-agent architecture,
Redis streams, and comprehensive monitoring.

Usage:
    python -m main run --mode paper --strategy momentum
    python -m main health
    python -m main slo --duration 60
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure structured logging
def setup_logging(level: str = "INFO") -> logging.Logger:
    """Setup structured logging with JSON format"""
    log_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create logs directory
    logs_dir = Path("logs")
    logs_dir.mkdir(exist_ok=True)
    
    # Configure logging
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(logs_dir / "crypto_ai_bot.log")
        ]
    )
    
    return logging.getLogger(__name__)

# Global state for graceful shutdown
_shutdown_requested = False
_logger = None

def signal_handler(signum, frame):
    """Handle graceful shutdown signals"""
    global _shutdown_requested
    _logger.info(f"Received signal {signum}, initiating graceful shutdown...")
    _shutdown_requested = True

async def run_command(args) -> None:
    """Run the trading bot with specified parameters"""
    _logger.info("Starting crypto AI bot in run mode")
    _logger.info(f"Mode: {args.mode}")
    _logger.info(f"Strategy: {args.strategy}")
    _logger.info(f"Config: {args.config}")
    _logger.info(f"Dry run: {args.dry_run}")

    # Start health endpoint immediately for Fly.io
    # Use shared state to allow health handler to access orchestrator
    health_state = {"orchestrator": None, "start_time": time.time()}

    from aiohttp import web
    import json as json_lib

    async def health_handler(request):
        """Health check with degraded status detection"""
        orchestrator = health_state.get("orchestrator")
        current_time = time.time()
        uptime = current_time - health_state["start_time"]

        response = {
            "status": "healthy",
            "mode": args.mode,
            "uptime_seconds": round(uptime, 2)
        }

        # Check publisher health if orchestrator is available
        if orchestrator and hasattr(orchestrator, 'signal_processor'):
            signal_processor = orchestrator.signal_processor
            if signal_processor and hasattr(signal_processor, 'resilient_publisher'):
                publisher = signal_processor.resilient_publisher
                if publisher:
                    stats = publisher.get_health_stats()
                    response["publisher"] = stats

                    # Degraded if no publish in >30s
                    if stats["last_publish_seconds_ago"] > 30:
                        response["status"] = "degraded"
                        response["reason"] = f"No publish in {stats['last_publish_seconds_ago']:.1f}s (>30s threshold)"

        # Add performance metrics if available
        metrics_publisher = health_state.get("metrics_publisher")
        if metrics_publisher:
            try:
                metrics_summary = metrics_publisher.get_latest_summary()
                if metrics_summary and metrics_summary.get("available"):
                    response["performance_metrics"] = {
                        "aggressive_mode_score": round(metrics_summary["aggressive_mode_score"]["value"], 2),
                        "velocity_to_target_pct": round(metrics_summary["velocity_to_target"]["percent"], 1),
                        "days_remaining": metrics_summary["days_remaining_estimate"]["value"],
                        "daily_rate_usd": round(metrics_summary["days_remaining_estimate"]["daily_rate"], 2),
                        "win_rate_pct": round(metrics_summary["trading_stats"]["win_rate"] * 100, 1),
                        "total_trades": metrics_summary["trading_stats"]["total_trades"],
                    }
            except Exception as e:
                _logger.debug(f"Could not fetch performance metrics: {e}")

        status_code = 200 if response["status"] == "healthy" else 503
        return web.Response(
            text=json_lib.dumps(response),
            content_type='application/json',
            status=status_code
        )

    app = web.Application()
    app.router.add_get('/health', health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8080)
    await site.start()
    _logger.info("✅ Health endpoint started on 0.0.0.0:8080 (degraded if no publish >30s)")

    # ===========================================
    # SECURITY & SAFETY CHECKS
    # ===========================================

    # 1. Check live trading guards
    from protections.kill_switches import check_live_trading_allowed, get_trading_mode

    trading_mode = get_trading_mode()
    _logger.info(f"Trading mode: {trading_mode.mode.upper()} (paper_mode={trading_mode.paper_mode})")

    if args.mode == "live":
        allowed, error = check_live_trading_allowed()
        if not allowed:
            _logger.error(f"🚨 LIVE TRADING BLOCKED: {error}")
            _logger.error("To enable live trading, set:")
            _logger.error("  MODE=live")
            _logger.error("  LIVE_TRADING_CONFIRMATION=I-accept-the-risk")
            sys.exit(1)
        _logger.warning("⚠️ LIVE TRADING ENABLED - Real money at risk!")
    else:
        _logger.info("✅ Paper mode active - no real orders will be placed")

    # 2. Initialize global kill switch
    from protections.kill_switches import GlobalKillSwitch
    kill_switch = GlobalKillSwitch()

    # Load configuration
    try:
        from config.unified_config_loader import load_system_config
        config = load_system_config(environment=args.mode)
        _logger.info("Configuration loaded successfully")
    except Exception as e:
        _logger.error(f"Failed to load configuration: {e}")
        sys.exit(1)

    # Initialize trading system
    try:
        _logger.info("Importing MasterOrchestrator...")
        from orchestration.master_orchestrator import MasterOrchestrator
        _logger.info("✅ MasterOrchestrator imported successfully")

        _logger.info("Creating MasterOrchestrator instance...")
        orchestrator = MasterOrchestrator(config_path=args.config)
        _logger.info("✅ MasterOrchestrator instance created")

        _logger.info("Initializing orchestrator (timeout: 60s)...")
        try:
            init_result = await asyncio.wait_for(
                orchestrator.initialize(),
                timeout=60.0
            )
            if not init_result:
                _logger.error("Failed to initialize orchestrator")
                sys.exit(1)
        except asyncio.TimeoutError:
            _logger.error("⏱️ Orchestrator initialization timed out after 60s")
            sys.exit(1)

        _logger.info("Trading system initialized successfully")

        # Store orchestrator in health state for health endpoint
        health_state["orchestrator"] = orchestrator

        # 3. Connect kill switch to Redis (if available)
        try:
            if hasattr(orchestrator, 'redis_client'):
                kill_switch.set_redis_client(orchestrator.redis_client)
                _logger.info("✅ Kill switch connected to Redis (control:halt_all)")
        except Exception as e:
            _logger.warning(f"Kill switch Redis connection failed: {e}")

        # Start the system
        await orchestrator.start()
        _logger.info("Trading system started")

        # Start performance metrics publisher (feature-flagged)
        metrics_publisher = None
        try:
            from metrics.metrics_publisher import create_metrics_publisher

            metrics_publisher = create_metrics_publisher(
                redis_manager=orchestrator.redis_manager if hasattr(orchestrator, 'redis_manager') else None,
                trade_manager=orchestrator.trade_manager if hasattr(orchestrator, 'trade_manager') else None,
                equity_tracker=orchestrator.equity_tracker if hasattr(orchestrator, 'equity_tracker') else None,
                logger=_logger,
                update_interval=30,
                auto_start=True,
            )
            health_state["metrics_publisher"] = metrics_publisher
            _logger.info("[OK] Performance metrics publisher started (update_interval=30s)")
        except Exception as e:
            _logger.warning(f"Performance metrics publisher not started: {e}")

        # Main trading loop with kill switch checks
        while not _shutdown_requested:
            try:
                # 4. Check kill switch before each cycle
                if not await kill_switch.is_trading_allowed():
                    status = kill_switch.get_status()
                    _logger.critical(f"🚨 TRADING HALTED BY KILL SWITCH: {status['reason']}")
                    _logger.critical("Trading paused. Deactivate kill switch to resume.")
                    await asyncio.sleep(10)  # Wait before checking again
                    continue

                # Simulate trading cycle
                _logger.info("Executing trading cycle...")
                await asyncio.sleep(1)  # Placeholder for actual trading logic

            except Exception as e:
                _logger.error(f"Trading cycle error: {e}")
                await asyncio.sleep(5)  # Wait before retry

        # Graceful shutdown
        if metrics_publisher:
            try:
                metrics_publisher.stop()
                _logger.info("Metrics publisher stopped")
            except Exception as e:
                _logger.warning(f"Error stopping metrics publisher: {e}")

        await orchestrator.stop()
        _logger.info("Trading system stopped gracefully")

    except Exception as e:
        _logger.error(f"Failed to run trading system: {e}")
        sys.exit(1)

async def health_command(args) -> None:
    """Check system health and Redis connectivity"""
    _logger.info("Running health check")
    
    health_status = {
        "timestamp": datetime.utcnow().isoformat(),
        "status": "unknown",
        "redis": {"connected": False, "error": None},
        "system": {"python_version": sys.version, "environment": os.getenv("ENVIRONMENT", "unknown")}
    }
    
    # Check Redis connectivity
    try:
        import redis
        from urllib.parse import urlparse
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _logger.info(f"Connecting to Redis: {redis_url}")
        
        # Parse URL to determine if TLS is needed
        parsed = urlparse(redis_url)
        use_ssl = parsed.scheme == "rediss"
        
        if use_ssl:
            # TLS connection
            import ssl
            ssl_context = ssl.create_default_context()
            ca_cert_path = os.getenv("REDIS_TLS_CERT_PATH", "/etc/ssl/certs/ca-certificates.crt")
            
            if os.path.exists(ca_cert_path):
                ssl_context.load_verify_locations(ca_cert_path)
            
            client = redis.from_url(
                redis_url,
                ssl_cert_reqs=ssl.CERT_REQUIRED,
                ssl_ca_certs=ca_cert_path,
                decode_responses=True
            )
        else:
            # Non-TLS connection
            client = redis.from_url(redis_url, decode_responses=True)
        
        # Test connection
        start_time = time.time()
        pong = client.ping()
        latency = (time.time() - start_time) * 1000
        
        if pong:
            health_status["redis"]["connected"] = True
            health_status["redis"]["latency_ms"] = round(latency, 2)
            health_status["redis"]["url"] = redis_url
            health_status["status"] = "healthy"
            _logger.info(f"Redis health check passed (latency: {latency:.2f}ms)")
        else:
            health_status["redis"]["error"] = "PING failed"
            health_status["status"] = "unhealthy"
            _logger.error("Redis PING failed")
            
    except Exception as e:
        health_status["redis"]["error"] = str(e)
        health_status["status"] = "unhealthy"
        _logger.error(f"Redis health check failed: {e}")
    
    # Output JSON result
    print(json.dumps(health_status, indent=2))
    
    # Exit with appropriate code
    if health_status["status"] == "healthy":
        sys.exit(0)
    else:
        sys.exit(1)

async def slo_command(args) -> None:
    """Simulate decision→publish timings and report SLO metrics"""
    _logger.info(f"Running SLO simulation for {args.duration} seconds")
    
    timings = []
    start_time = time.time()
    
    try:
        # Simulate decision→publish cycles
        while time.time() - start_time < args.duration and not _shutdown_requested:
            cycle_start = time.time()
            
            # Simulate decision making
            await asyncio.sleep(0.01)  # 10ms decision time
            
            # Simulate publish operation
            await asyncio.sleep(0.005)  # 5ms publish time
            
            cycle_end = time.time()
            total_latency = (cycle_end - cycle_start) * 1000  # Convert to ms
            timings.append(total_latency)
            
            _logger.debug(f"Cycle latency: {total_latency:.2f}ms")
            
            # Small delay between cycles
            await asyncio.sleep(0.1)
    
    except KeyboardInterrupt:
        _logger.info("SLO simulation interrupted by user")
    
    # Calculate statistics
    if timings:
        timings.sort()
        p50 = timings[len(timings) // 2]
        p95 = timings[int(len(timings) * 0.95)]
        p99 = timings[int(len(timings) * 0.99)]
        
        slo_report = {
            "timestamp": datetime.utcnow().isoformat(),
            "duration_seconds": args.duration,
            "total_cycles": len(timings),
            "latency_stats": {
                "min_ms": round(min(timings), 2),
                "max_ms": round(max(timings), 2),
                "avg_ms": round(sum(timings) / len(timings), 2),
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2)
            },
            "slo_compliance": {
                "p95_under_500ms": p95 < 500,
                "p50_under_100ms": p50 < 100
            }
        }
        
        print(json.dumps(slo_report, indent=2))
        
        # Check SLO compliance
        if slo_report["slo_compliance"]["p95_under_500ms"]:
            _logger.info("✅ SLO compliance: P95 latency under 500ms")
            sys.exit(0)
        else:
            _logger.warning("❌ SLO violation: P95 latency exceeds 500ms")
            sys.exit(1)
    else:
        _logger.error("No timing data collected")
        sys.exit(1)

def validate_mode(mode: str) -> bool:
    """Validate trading mode"""
    valid_modes = ["paper", "live"]
    if mode not in valid_modes:
        print(f"Error: Invalid mode '{mode}'. Must be one of: {', '.join(valid_modes)}")
        return False
    return True

def cli() -> None:
    """Main CLI entry point"""
    global _logger
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create argument parser
    parser = argparse.ArgumentParser(
        description="Crypto AI Bot - Production Trading System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m main run --mode paper --strategy momentum
  python -m main health
  python -m main slo --duration 60
        """
    )
    
    # Add subcommands
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Run subcommand
    run_parser = subparsers.add_parser("run", help="Run the trading bot")
    run_parser.add_argument(
        "--mode", 
        choices=["paper", "live"], 
        default="paper",
        help="Trading mode (default: paper)"
    )
    run_parser.add_argument(
        "--config",
        default="config/settings.yaml",
        help="Configuration file path (default: config/settings.yaml)"
    )
    run_parser.add_argument(
        "--strategy",
        default="momentum",
        help="Trading strategy to use (default: momentum)"
    )
    run_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate trading without executing orders"
    )
    
    # Health subcommand
    health_parser = subparsers.add_parser("health", help="Check system health")
    
    # SLO subcommand
    slo_parser = subparsers.add_parser("slo", help="Run SLO simulation")
    slo_parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Simulation duration in seconds (default: 60)"
    )
    
    # Parse arguments
    args = parser.parse_args()
    
    # Setup logging
    log_level = os.getenv("LOG_LEVEL", "INFO")
    _logger = setup_logging(log_level)
    
    # Validate mode if provided
    if hasattr(args, 'mode') and not validate_mode(args.mode):
        sys.exit(1)
    
    # Run appropriate command
    try:
        if args.command == "run":
            asyncio.run(run_command(args))
        elif args.command == "health":
            asyncio.run(health_command(args))
        elif args.command == "slo":
            asyncio.run(slo_command(args))
        else:
            parser.print_help()
            sys.exit(1)
    except KeyboardInterrupt:
        _logger.info("Received keyboard interrupt, shutting down...")
        sys.exit(0)
    except Exception as e:
        _logger.error(f"Command failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    cli()