# -*- coding: utf-8 -*-
"""
Configure System for Live Trading

This script:
1. Updates .env file to set MODE=LIVE and LIVE_TRADING_CONFIRMATION
2. Updates ACTIVE_SIGNALS in Redis to point to signals:live
3. Validates all safety gates are enabled
4. Creates backup of current configuration

IMPORTANT: This script will enable REAL MONEY trading. Use with caution!

Usage:
    python scripts/configure_live_trading.py [--confirm]

Options:
    --confirm    Actually apply changes (without this, runs in dry-run mode)
"""

import os
import sys
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    from dotenv import load_dotenv, set_key
except ImportError as e:
    print(f"[ERROR] Missing dependencies: {e}")
    print("Install with: pip install redis python-dotenv")
    sys.exit(1)


class LiveTradingConfigurator:
    """Configures system for live trading mode"""

    def __init__(self, dry_run: bool = True):
        self.dry_run = dry_run
        self.env_file = project_root / ".env"
        self.backup_dir = project_root / "config" / "backups"
        self.redis_client = None
        self.changes: List[str] = []

    def run(self) -> bool:
        """Run the configuration process"""

        print("\n" + "="*70)
        if self.dry_run:
            print(" LIVE TRADING CONFIGURATION (DRY RUN)")
        else:
            print(" LIVE TRADING CONFIGURATION (APPLYING CHANGES)")
        print("="*70 + "\n")

        if not self.dry_run:
            print("[WARNING] This will enable REAL MONEY trading!")
            response = input("Type 'I understand the risk' to proceed: ")
            if response != "I understand the risk":
                print("[ABORTED] Configuration cancelled")
                return False

        # Run configuration steps
        steps = [
            ("Backup current configuration", self.backup_config),
            ("Load environment variables", self.load_env),
            ("Connect to Redis", self.connect_redis),
            ("Update MODE to LIVE", self.update_mode),
            ("Set LIVE_TRADING_CONFIRMATION", self.set_confirmation),
            ("Update ACTIVE_SIGNALS in Redis", self.update_redis_routing),
            ("Verify safety gates", self.verify_safety_gates),
            ("Update settings.yaml", self.update_settings_yaml),
        ]

        for step_name, step_func in steps:
            print(f"\n[STEP] {step_name}")
            print("-" * 70)

            try:
                result = step_func()
                if not result:
                    print(f"[FAILED] {step_name} failed")
                    return False
                print(f"[OK] {step_name} completed")
            except Exception as e:
                print(f"[ERROR] {step_name}: {e}")
                return False

        # Print summary
        self.print_summary()

        return True

    def backup_config(self) -> bool:
        """Backup current configuration"""

        if self.dry_run:
            print("[DRY RUN] Would create backup of .env and settings.yaml")
            return True

        try:
            # Create backup directory
            self.backup_dir.mkdir(parents=True, exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

            # Backup .env
            if self.env_file.exists():
                backup_env = self.backup_dir / f".env.backup_{timestamp}"
                shutil.copy2(self.env_file, backup_env)
                print(f"   Backed up .env to: {backup_env.name}")
                self.changes.append(f"Backed up .env to {backup_env.name}")

            # Backup settings.yaml
            settings_file = project_root / "config" / "settings.yaml"
            if settings_file.exists():
                backup_settings = self.backup_dir / f"settings.yaml.backup_{timestamp}"
                shutil.copy2(settings_file, backup_settings)
                print(f"   Backed up settings.yaml to: {backup_settings.name}")
                self.changes.append(f"Backed up settings.yaml to {backup_settings.name}")

            return True

        except Exception as e:
            print(f"   Error creating backup: {e}")
            return False

    def load_env(self) -> bool:
        """Load environment variables"""

        if not self.env_file.exists():
            print(f"   [ERROR] .env file not found: {self.env_file}")
            return False

        load_dotenv(self.env_file)
        print(f"   Loaded environment from: {self.env_file.name}")

        return True

    def connect_redis(self) -> bool:
        """Connect to Redis"""

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

            self.redis_client = redis.from_url(redis_url, **conn_params)
            self.redis_client.ping()

            print(f"   Connected to Redis: {redis_url[:30]}...")

            return True

        except Exception as e:
            print(f"   [ERROR] Redis connection failed: {e}")
            return False

    def update_mode(self) -> bool:
        """Update MODE to LIVE in .env"""

        if self.dry_run:
            print("[DRY RUN] Would set MODE=LIVE in .env")
            self.changes.append("Set MODE=LIVE")
            return True

        try:
            # Check current mode
            current_mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE")
            print(f"   Current MODE: {current_mode}")

            # Update MODE in .env
            set_key(str(self.env_file), "MODE", "LIVE")
            print("   Set MODE=LIVE in .env")
            self.changes.append("Set MODE=LIVE in .env")

            # Also update BOT_MODE for compatibility
            set_key(str(self.env_file), "BOT_MODE", "LIVE")
            print("   Set BOT_MODE=LIVE in .env")

            # Update ACTIVE_SIGNALS_STREAM
            set_key(str(self.env_file), "ACTIVE_SIGNALS_STREAM", "signals:live")
            print("   Set ACTIVE_SIGNALS_STREAM=signals:live")
            self.changes.append("Set ACTIVE_SIGNALS_STREAM=signals:live")

            return True

        except Exception as e:
            print(f"   [ERROR] Failed to update MODE: {e}")
            return False

    def set_confirmation(self) -> bool:
        """Set LIVE_TRADING_CONFIRMATION"""

        if self.dry_run:
            print("[DRY RUN] Would set LIVE_TRADING_CONFIRMATION=I-accept-the-risk")
            self.changes.append("Set LIVE_TRADING_CONFIRMATION=I-accept-the-risk")
            return True

        try:
            confirmation_phrase = "I-accept-the-risk"
            set_key(str(self.env_file), "LIVE_TRADING_CONFIRMATION", confirmation_phrase)
            print(f"   Set LIVE_TRADING_CONFIRMATION={confirmation_phrase}")
            self.changes.append(f"Set LIVE_TRADING_CONFIRMATION={confirmation_phrase}")

            return True

        except Exception as e:
            print(f"   [ERROR] Failed to set confirmation: {e}")
            return False

    def update_redis_routing(self) -> bool:
        """Update ACTIVE_SIGNALS in Redis to point to signals:live"""

        if not self.redis_client:
            print("   [ERROR] Redis not connected")
            return False

        if self.dry_run:
            print("[DRY RUN] Would set ACTIVE_SIGNALS -> signals:live in Redis")
            self.changes.append("Set ACTIVE_SIGNALS -> signals:live in Redis")
            return True

        try:
            # Get current value
            current = self.redis_client.get("ACTIVE_SIGNALS")
            if current:
                current_str = current.decode() if isinstance(current, bytes) else current
                print(f"   Current ACTIVE_SIGNALS: {current_str}")

            # Set new value
            self.redis_client.set("ACTIVE_SIGNALS", "signals:live")
            print("   Set ACTIVE_SIGNALS -> signals:live")
            self.changes.append("Set ACTIVE_SIGNALS -> signals:live in Redis")

            # Verify
            new_value = self.redis_client.get("ACTIVE_SIGNALS")
            new_value_str = new_value.decode() if isinstance(new_value, bytes) else new_value
            print(f"   Verified ACTIVE_SIGNALS: {new_value_str}")

            return True

        except Exception as e:
            print(f"   [ERROR] Failed to update Redis routing: {e}")
            return False

    def verify_safety_gates(self) -> bool:
        """Verify safety gates are configured"""

        print("   Checking safety gate configuration...")

        # Check emergency stop is NOT active
        emergency_stop = os.getenv("KRAKEN_EMERGENCY_STOP", "").lower()
        if emergency_stop in ("true", "1", "yes"):
            print("   [WARNING] KRAKEN_EMERGENCY_STOP is ACTIVE")
            print("   This will block all new trades!")
            return False

        print("   [OK] Emergency stop: inactive")

        # Check risk config exists
        settings_file = project_root / "config" / "settings.yaml"
        if not settings_file.exists():
            print("   [WARNING] settings.yaml not found")
            return True  # Not critical

        try:
            import yaml
            with open(settings_file, "r") as f:
                settings = yaml.safe_load(f)

            risk = settings.get("risk", {})

            # Check key risk parameters
            checks = [
                ("max_concurrent_positions", risk.get("max_concurrent_positions")),
                ("risk_per_trade_pct", risk.get("risk_per_trade_pct")),
                ("day_max_drawdown_pct", risk.get("day_max_drawdown_pct")),
                ("rolling_max_drawdown_pct", risk.get("rolling_max_drawdown_pct")),
            ]

            for param_name, param_value in checks:
                if param_value:
                    print(f"   [OK] {param_name}: {param_value}")
                else:
                    print(f"   [WARNING] {param_name} not configured")

        except Exception as e:
            print(f"   [WARNING] Could not read settings.yaml: {e}")

        return True

    def update_settings_yaml(self) -> bool:
        """Update mode in settings.yaml (optional, since env takes precedence)"""

        settings_file = project_root / "config" / "settings.yaml"
        if not settings_file.exists():
            print("   [INFO] settings.yaml not found, skipping")
            return True

        if self.dry_run:
            print("[DRY RUN] Would set mode: LIVE in settings.yaml")
            return True

        try:
            import yaml

            with open(settings_file, "r") as f:
                settings = yaml.safe_load(f)

            # Update mode
            settings["mode"] = "LIVE"

            with open(settings_file, "w") as f:
                yaml.safe_dump(settings, f, default_flow_style=False, sort_keys=False)

            print("   Set mode: LIVE in settings.yaml")
            self.changes.append("Set mode: LIVE in settings.yaml")

            return True

        except Exception as e:
            print(f"   [WARNING] Could not update settings.yaml: {e}")
            return True  # Not critical

    def print_summary(self):
        """Print configuration summary"""

        print("\n" + "="*70)
        print(" CONFIGURATION SUMMARY")
        print("="*70 + "\n")

        if self.dry_run:
            print("[DRY RUN MODE] No changes were made")
            print("\nChanges that would be applied:")
        else:
            print("[LIVE MODE] Changes applied:")

        for i, change in enumerate(self.changes, 1):
            print(f"   {i}. {change}")

        print("\n" + "="*70)

        if not self.dry_run:
            print("\n[SUCCESS] System configured for LIVE trading")
            print("\n[IMPORTANT] Next steps:")
            print("   1. Restart the trading system to apply changes")
            print("   2. Verify MODE=LIVE in startup logs")
            print("   3. Monitor signals:live stream for new signals")
            print("   4. Start with small position sizes")
            print("   5. Keep emergency stop procedure ready")
            print("\n[EMERGENCY STOP]")
            print("   To immediately halt trading, set in .env:")
            print("   KRAKEN_EMERGENCY_STOP=true")
        else:
            print("\n[INFO] Run with --confirm to apply these changes")

        print("\n" + "="*70 + "\n")


def main():
    """Main entry point"""

    # Check for --confirm flag
    confirm = "--confirm" in sys.argv

    configurator = LiveTradingConfigurator(dry_run=not confirm)

    try:
        success = configurator.run()

        # Cleanup
        if configurator.redis_client:
            configurator.redis_client.close()

        sys.exit(0 if success else 1)

    except KeyboardInterrupt:
        print("\n\n[ABORTED] Configuration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
