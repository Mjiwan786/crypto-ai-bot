# -*- coding: utf-8 -*-
"""
Kraken Scalper Agent - CLI Entry Point

Allows running the agent directly:
    python agents/scalper/kraken_scalper_agent.py --mode live

Or as a module:
    python -m agents.scalper --mode live
"""

import argparse
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from agents.scalper.kraken_scalper_agent import KrakenScalperAgent
from dotenv import load_dotenv


async def main():
    """Main entry point for CLI"""

    # Parse arguments
    parser = argparse.ArgumentParser(description="Kraken Scalper Agent")
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Trading mode (paper or live)"
    )
    parser.add_argument(
        "--config",
        default="config/enhanced_scalper_config.yaml",
        help="Path to config file"
    )
    args = parser.parse_args()

    print("\n" + "="*70)
    print(f" KRAKEN SCALPER AGENT - {args.mode.upper()} MODE")
    print("="*70 + "\n")

    # Load environment
    env_file = project_root / ".env"
    if env_file.exists():
        load_dotenv(env_file)
        print(f"[OK] Loaded environment from .env")
    else:
        print(f"[WARNING] .env file not found at: {env_file}")

    # Validate mode configuration
    import os
    current_mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")

    if args.mode.upper() != current_mode.upper():
        print(f"\n[WARNING] CLI mode ({args.mode}) doesn't match .env MODE ({current_mode})")
        print(f"          Using .env MODE: {current_mode}")
        print(f"          To change, update MODE in .env or run:")
        print(f"          python scripts/configure_live_trading.py --confirm\n")

    # Check for LIVE mode confirmation
    if current_mode.upper() == "LIVE":
        confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
        expected = "I-accept-the-risk"

        if confirmation != expected:
            print(f"\n[ERROR] LIVE mode requires LIVE_TRADING_CONFIRMATION='{expected}'")
            print(f"        Current value: '{confirmation}'")
            print(f"\nTo enable live trading, run:")
            print(f"    python scripts/configure_live_trading.py --confirm\n")
            sys.exit(1)

        print(f"[OK] LIVE mode confirmation verified")

    # Check emergency stop
    emergency_stop = os.getenv("KRAKEN_EMERGENCY_STOP", "").lower()
    if emergency_stop in ("true", "1", "yes"):
        print("\n[ERROR] KRAKEN_EMERGENCY_STOP is ACTIVE")
        print("        All new trades are blocked!")
        print(f"\nTo disable, set in .env:")
        print(f"    KRAKEN_EMERGENCY_STOP=false\n")
        sys.exit(1)

    print(f"[OK] Emergency stop: inactive\n")

    # Check config file
    config_path = project_root / args.config
    if not config_path.exists():
        # Try fallback
        config_path = project_root / "agents" / "scalper" / "config" / "settings.yaml"
        if not config_path.exists():
            print(f"[ERROR] Config file not found: {args.config}")
            sys.exit(1)
        print(f"[INFO] Using fallback config: {config_path.relative_to(project_root)}")
    else:
        print(f"[INFO] Using config: {config_path.relative_to(project_root)}")

    # Create and start agent
    try:
        print("\n[STARTING] Creating agent instance...")
        agent = KrakenScalperAgent(config_path=str(config_path))

        print("[STARTING] Initializing agent...")
        success = await agent.startup()

        if not success:
            print("\n[ERROR] Agent startup failed")
            sys.exit(1)

        print("\n[OK] Agent started successfully")
        print(f"[INFO] Agent state: {agent.state.value}")

        # Get signal stream
        stream_key = f"signals:{current_mode.lower()}"
        print(f"[INFO] Publishing signals to: {stream_key}")

        print("\n" + "-"*70)
        print(" AGENT RUNNING - Press Ctrl+C to stop")
        print("-"*70 + "\n")

        # Keep agent running
        try:
            while True:
                await asyncio.sleep(10)

                # Show health status
                try:
                    health = await agent.get_health_status()
                    print(f"[HEALTH] State: {health.get('state')}, "
                          f"Positions: {health.get('active_positions')}, "
                          f"Trades: {health.get('trades_today')}, "
                          f"PnL: ${health.get('pnl', 0):.2f}")
                except Exception as e:
                    print(f"[WARNING] Health check error: {e}")

        except KeyboardInterrupt:
            print("\n\n[STOPPING] Shutting down agent...")
            await agent.shutdown()
            print("[OK] Agent shutdown complete\n")

    except Exception as e:
        print(f"\n[ERROR] Agent error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
