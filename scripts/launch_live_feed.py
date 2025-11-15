# -*- coding: utf-8 -*-
"""
Launch Real-Time Feed & Signal Publishing Pipeline

This script launches the Kraken WebSocket → Scalper → Redis → API → Site pipeline
in LIVE mode and monitors signal flow through all layers.

Usage:
    python scripts/launch_live_feed.py [--dry-run]

Options:
    --dry-run    Run without actually starting agents (validation only)

Environment:
    Requires conda environment: crypto-bot
    Requires .env configured for LIVE mode
"""

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Optional

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from dotenv import load_dotenv
except ImportError as e:
    print(f"[ERROR] Missing dependencies: {e}")
    print("Install with: pip install redis python-dotenv")
    sys.exit(1)


class LiveFeedLauncher:
    """Launches and monitors the live trading feed pipeline"""

    def __init__(self, dry_run: bool = False):
        self.dry_run = dry_run
        self.redis_client: Optional[redis.Redis] = None
        self.env_file = project_root / ".env"

    async def run(self) -> bool:
        """Run the launcher"""

        print("\n" + "="*70)
        if self.dry_run:
            print(" LIVE FEED LAUNCHER (DRY RUN)")
        else:
            print(" LIVE FEED LAUNCHER (STARTING PIPELINE)")
        print("="*70 + "\n")

        # Run validation steps
        if not await self.validate_environment():
            print("\n[ERROR] Environment validation failed")
            return False

        if not await self.validate_redis():
            print("\n[ERROR] Redis validation failed")
            return False

        if not await self.validate_mode():
            print("\n[ERROR] Mode validation failed")
            return False

        if self.dry_run:
            print("\n[DRY RUN] Validation complete - would start agents")
            print("\nTo start live feed, run without --dry-run:")
            print("    python scripts/launch_live_feed.py")
            return True

        # Start the pipeline
        print("\n[START] Launching live feed pipeline...")
        return await self.start_pipeline()

    async def validate_environment(self) -> bool:
        """Validate environment configuration"""

        print("[CHECK] Validating environment configuration...")

        # Load .env
        if not self.env_file.exists():
            print(f"   [ERROR] .env file not found: {self.env_file}")
            return False

        load_dotenv(self.env_file)
        print(f"   [OK] Loaded .env")

        # Check required variables
        required_vars = {
            "REDIS_URL": os.getenv("REDIS_URL"),
            "KRAKEN_API_KEY": os.getenv("KRAKEN_API_KEY"),
            "KRAKEN_API_SECRET": os.getenv("KRAKEN_API_SECRET"),
        }

        for var_name, var_value in required_vars.items():
            if not var_value:
                print(f"   [ERROR] {var_name} not set")
                return False
            print(f"   [OK] {var_name} configured")

        return True

    async def validate_redis(self) -> bool:
        """Validate Redis connectivity"""

        print("\n[CHECK] Validating Redis Cloud connectivity...")

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            print("   [ERROR] REDIS_URL not set")
            return False

        try:
            conn_params = {
                "decode_responses": True,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
            }

            # Add CA cert if available
            ca_cert = os.getenv("REDIS_CA_CERT_PATH") or os.getenv("REDIS_CA_CERT")
            if redis_url.startswith("rediss://") and ca_cert:
                ca_cert_path = project_root / ca_cert
                if ca_cert_path.exists():
                    conn_params["ssl_ca_certs"] = str(ca_cert_path)
                    print(f"   [OK] Using CA cert: {ca_cert}")

            self.redis_client = redis.from_url(redis_url, **conn_params)
            self.redis_client.ping()
            print(f"   [OK] Redis connected (PING OK)")

            # Check stream configuration
            active_signals = self.redis_client.get("ACTIVE_SIGNALS")
            if active_signals:
                active_str = active_signals.decode() if isinstance(active_signals, bytes) else active_signals
                print(f"   [OK] ACTIVE_SIGNALS -> {active_str}")
            else:
                print(f"   [WARNING] ACTIVE_SIGNALS not set in Redis")

            return True

        except Exception as e:
            print(f"   [ERROR] Redis connection failed: {e}")
            return False

    async def validate_mode(self) -> bool:
        """Validate trading mode configuration"""

        print("\n[CHECK] Validating trading mode...")

        # Check MODE
        mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
        print(f"   Current MODE: {mode}")

        if mode.upper() == "LIVE":
            print("   [WARNING] LIVE mode - real money trading!")

            # Check confirmation
            confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
            expected = "I-accept-the-risk"

            if confirmation != expected:
                print(f"   [ERROR] LIVE mode requires LIVE_TRADING_CONFIRMATION='{expected}'")
                return False

            print(f"   [OK] LIVE_TRADING_CONFIRMATION verified")
        else:
            print("   [INFO] PAPER mode - simulated trading")

        # Check emergency stop
        emergency_stop = os.getenv("KRAKEN_EMERGENCY_STOP", "").lower()
        if emergency_stop in ("true", "1", "yes"):
            print("   [ERROR] KRAKEN_EMERGENCY_STOP is ACTIVE - trading blocked!")
            return False

        print("   [OK] Emergency stop: inactive")

        return True

    async def start_pipeline(self) -> bool:
        """Start the trading pipeline"""

        print("\n[STARTING] Initializing trading components...")

        try:
            # Import agent modules
            from agents.scalper.kraken_scalper_agent import KrakenScalperAgent

            print("   [OK] Imported KrakenScalperAgent")

            # Create agent instance
            config_path = "config/enhanced_scalper_config.yaml"
            if not (project_root / config_path).exists():
                # Fallback to default config
                config_path = "agents/scalper/config/settings.yaml"

            print(f"   [INFO] Using config: {config_path}")

            agent = KrakenScalperAgent(config_path=config_path)
            print("   [OK] Created agent instance")

            # Start agent
            print("\n[STARTING] Starting Kraken Scalper Agent...")
            success = await agent.startup()

            if not success:
                print("   [ERROR] Agent startup failed")
                return False

            print("   [OK] Agent started successfully")
            print(f"   [INFO] Agent state: {agent.state.value}")

            # Monitor pipeline
            print("\n[MONITORING] Starting pipeline monitoring...")
            await self.monitor_pipeline(agent)

            return True

        except KeyboardInterrupt:
            print("\n\n[STOPPED] Pipeline stopped by user")
            return True
        except Exception as e:
            print(f"\n[ERROR] Failed to start pipeline: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def monitor_pipeline(self, agent):
        """Monitor the pipeline and signal flow"""

        mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
        stream_key = f"signals:{mode.lower()}"

        print(f"\n[MONITOR] Monitoring {stream_key} stream...")
        print(f"[MONITOR] Press Ctrl+C to stop\n")

        last_signal_count = 0
        start_time = time.time()

        try:
            while True:
                await asyncio.sleep(5)  # Check every 5 seconds

                # Get agent health
                try:
                    health = await agent.get_health_status()
                    print(f"\n[HEALTH] Agent State: {health.get('state', 'unknown')}")
                    print(f"         Active Positions: {health.get('active_positions', 0)}")
                    print(f"         Trades Today: {health.get('trades_today', 0)}")
                    print(f"         PnL: ${health.get('pnl', 0):.2f}")
                except Exception as e:
                    print(f"[WARNING] Could not get health status: {e}")

                # Check signals stream
                try:
                    if self.redis_client:
                        stream_length = self.redis_client.xlen(stream_key)
                        new_signals = stream_length - last_signal_count

                        if new_signals > 0:
                            print(f"\n[SIGNALS] {new_signals} new signal(s) published to {stream_key}")

                            # Read latest signal
                            signals = self.redis_client.xrevrange(stream_key, count=1)
                            if signals:
                                entry_id, fields = signals[0]
                                print(f"          Entry ID: {entry_id}")
                                print(f"          Pair: {fields.get('pair', 'unknown')}")
                                print(f"          Side: {fields.get('side', 'unknown')}")
                                print(f"          Strategy: {fields.get('strategy', 'unknown')}")
                                print(f"          Confidence: {fields.get('confidence', '0')}")

                        last_signal_count = stream_length

                        # Show stream stats
                        runtime = time.time() - start_time
                        rate = stream_length / runtime if runtime > 0 else 0
                        print(f"\n[STATS] Stream: {stream_key}")
                        print(f"        Total signals: {stream_length}")
                        print(f"        Signal rate: {rate:.2f} signals/sec")
                        print(f"        Runtime: {runtime:.0f}s")

                except Exception as e:
                    print(f"[WARNING] Could not check stream: {e}")

                print("-" * 70)

        except KeyboardInterrupt:
            print("\n\n[STOPPING] Shutting down agent...")
            try:
                await agent.shutdown()
                print("[OK] Agent shutdown complete")
            except Exception as e:
                print(f"[ERROR] Shutdown error: {e}")

    def print_summary(self):
        """Print summary"""

        print("\n" + "="*70)
        print(" PIPELINE SUMMARY")
        print("="*70 + "\n")

        mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")

        print(f"Trading Mode: {mode}")
        print(f"Signal Stream: signals:{mode.lower()}")
        print(f"Redis: Connected")

        if self.redis_client:
            try:
                stream_length = self.redis_client.xlen(f"signals:{mode.lower()}")
                print(f"Signals Published: {stream_length}")
            except:
                pass

        print("\n" + "="*70 + "\n")


async def main_async():
    """Async main entry point"""

    # Check for --dry-run flag
    dry_run = "--dry-run" in sys.argv

    launcher = LiveFeedLauncher(dry_run=dry_run)

    try:
        success = await launcher.run()
        sys.exit(0 if success else 1)
    finally:
        if launcher.redis_client:
            launcher.redis_client.close()


def main():
    """Main entry point"""

    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n[ABORTED] Launcher stopped by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
