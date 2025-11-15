"""
Validate Live Trading Setup

Comprehensive validation script that checks:
1. Environment configuration (MODE, LIVE_TRADING_CONFIRMATION)
2. Redis Cloud connectivity with TLS
3. Stream configuration (signals:live, signals:paper)
4. Safety gates (emergency stop, risk controls)
5. Config file alignment
6. Write test signal to verify stream routing

Usage:
    python scripts/validate_live_trading_setup.py

    Or with conda:
    conda activate crypto-bot && python scripts/validate_live_trading_setup.py
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import logging

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

try:
    import redis
    import yaml
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing dependencies: {e}")
    print("Install with: pip install redis pyyaml python-dotenv")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LiveTradingValidator:
    """Validates live trading setup and configuration"""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.redis_client = None

    def run_all_checks(self) -> bool:
        """
        Run all validation checks.

        Returns:
            True if all checks pass, False otherwise
        """
        print("\n" + "="*80)
        print("LIVE TRADING SETUP VALIDATION")
        print("="*80 + "\n")

        checks = [
            ("Environment Configuration", self.check_environment),
            ("Redis Cloud Connectivity", self.check_redis_connectivity),
            ("Stream Configuration", self.check_stream_configuration),
            ("Config File Alignment", self.check_config_alignment),
            ("Safety Gates", self.check_safety_gates),
            ("Write Test Signal", self.test_signal_write),
        ]

        for check_name, check_func in checks:
            print(f"\n{'-'*80}")
            print(f"[CHECK] {check_name}")
            print(f"{'-'*80}")

            try:
                check_func()
            except Exception as e:
                self.errors.append(f"{check_name}: {str(e)}")
                print(f"[FAILED] {str(e)}")

        # Print summary
        self.print_summary()

        return len(self.errors) == 0

    def check_environment(self):
        """Check environment variables for live trading"""

        # Load .env file
        env_file = project_root / ".env"
        if not env_file.exists():
            self.errors.append(".env file not found")
            print(f"❌ .env file not found at: {env_file}")
            return

        load_dotenv(env_file)
        print(f"✅ Loaded .env from: {env_file}")

        # Check MODE / TRADING_MODE / BOT_MODE (multiple variations used in codebase)
        mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE")

        if not mode:
            self.errors.append("MODE/TRADING_MODE/BOT_MODE not set in environment")
            print("❌ No MODE variable found (checked: MODE, TRADING_MODE, BOT_MODE)")
        else:
            print(f"✅ Trading mode: {mode}")

            if mode.upper() == "LIVE":
                print("   ⚠️  LIVE mode detected - real money trading!")

                # Check LIVE_TRADING_CONFIRMATION
                confirmation = os.getenv("LIVE_TRADING_CONFIRMATION", "")
                expected = "I-accept-the-risk"

                if confirmation != expected:
                    self.errors.append(
                        f"LIVE mode requires LIVE_TRADING_CONFIRMATION='{expected}' "
                        f"(current: '{confirmation}')"
                    )
                    print(f"❌ LIVE_TRADING_CONFIRMATION not set correctly")
                    print(f"   Expected: {expected}")
                    print(f"   Current:  {confirmation}")
                else:
                    print(f"✅ LIVE_TRADING_CONFIRMATION verified")
            elif mode.upper() == "PAPER":
                print("   ℹ️  PAPER mode - simulated trading (safe)")
            else:
                self.warnings.append(f"Unknown MODE value: {mode}")
                print(f"⚠️  Unknown MODE value: {mode}")

        # Check Redis URL
        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            self.errors.append("REDIS_URL not set")
            print("❌ REDIS_URL not found")
        else:
            # Check if TLS is enabled
            if redis_url.startswith("rediss://"):
                print(f"✅ Redis TLS enabled (rediss://)")

                # Check CA cert path
                ca_cert = os.getenv("REDIS_CA_CERT_PATH") or os.getenv("REDIS_CA_CERT")
                if ca_cert:
                    ca_cert_path = project_root / ca_cert
                    if ca_cert_path.exists():
                        print(f"✅ CA certificate found: {ca_cert}")
                    else:
                        self.warnings.append(f"CA certificate not found: {ca_cert_path}")
                        print(f"⚠️  CA certificate not found: {ca_cert_path}")
                else:
                    self.warnings.append("REDIS_CA_CERT_PATH not set (may use certifi)")
                    print("⚠️  REDIS_CA_CERT_PATH not set (will use certifi)")
            else:
                self.warnings.append("Redis URL does not use TLS (rediss://)")
                print(f"⚠️  Redis URL does not use TLS: {redis_url[:20]}...")

        # Check stream names
        signals_paper = os.getenv("STREAM_SIGNALS_PAPER") or os.getenv("REDIS_STREAM_SIGNALS_PAPER")
        signals_live = os.getenv("STREAM_SIGNALS_LIVE") or os.getenv("REDIS_STREAM_SIGNALS_LIVE")

        if signals_paper == "signals:paper":
            print(f"✅ STREAM_SIGNALS_PAPER: {signals_paper}")
        else:
            self.warnings.append(f"STREAM_SIGNALS_PAPER should be 'signals:paper', got: {signals_paper}")
            print(f"⚠️  STREAM_SIGNALS_PAPER: {signals_paper} (expected: signals:paper)")

        if signals_live == "signals:live":
            print(f"✅ STREAM_SIGNALS_LIVE: {signals_live}")
        else:
            self.warnings.append(f"STREAM_SIGNALS_LIVE should be 'signals:live', got: {signals_live}")
            print(f"⚠️  STREAM_SIGNALS_LIVE: {signals_live} (expected: signals:live)")

        # Check emergency stop
        emergency_stop = os.getenv("KRAKEN_EMERGENCY_STOP", "").lower()
        if emergency_stop in ("true", "1", "yes"):
            self.warnings.append("KRAKEN_EMERGENCY_STOP is active - no new trades allowed")
            print("⚠️  KRAKEN_EMERGENCY_STOP is ACTIVE - new entries blocked")
        else:
            print("✅ Emergency stop: inactive")

    def check_redis_connectivity(self):
        """Test Redis Cloud connectivity with TLS"""

        redis_url = os.getenv("REDIS_URL")
        if not redis_url:
            self.errors.append("Cannot test Redis - REDIS_URL not set")
            print("❌ REDIS_URL not set, skipping connectivity test")
            return

        try:
            # Build connection parameters
            conn_params = {
                "decode_responses": True,
                "socket_timeout": 5,
                "socket_connect_timeout": 5,
            }

            # Add TLS if rediss://
            if redis_url.startswith("rediss://"):
                conn_params["ssl"] = True

                # Try to find CA cert
                ca_cert = os.getenv("REDIS_CA_CERT_PATH") or os.getenv("REDIS_CA_CERT")
                if ca_cert:
                    ca_cert_path = project_root / ca_cert
                    if ca_cert_path.exists():
                        conn_params["ssl_ca_certs"] = str(ca_cert_path)
                        conn_params["ssl_cert_reqs"] = "required"
                        print(f"   Using CA cert: {ca_cert}")
                else:
                    # Use certifi
                    conn_params["ssl_cert_reqs"] = "required"
                    print(f"   Using certifi for CA validation")

            # Create client
            print(f"   Connecting to: {redis_url[:30]}...")
            self.redis_client = redis.from_url(redis_url, **conn_params)

            # Test connection
            self.redis_client.ping()
            print("✅ Redis connection successful (PING OK)")

            # Get info
            info = self.redis_client.info("server")
            print(f"✅ Redis version: {info.get('redis_version', 'unknown')}")
            print(f"✅ Redis mode: {info.get('redis_mode', 'unknown')}")

        except redis.ConnectionError as e:
            self.errors.append(f"Redis connection failed: {str(e)}")
            print(f"❌ Connection failed: {str(e)}")
        except Exception as e:
            self.errors.append(f"Redis error: {str(e)}")
            print(f"❌ Error: {str(e)}")

    def check_stream_configuration(self):
        """Check Redis stream configuration"""

        if not self.redis_client:
            self.warnings.append("Redis not connected, skipping stream checks")
            print("⚠️  Redis not connected, skipping stream checks")
            return

        try:
            # Check if signals:paper stream exists
            try:
                paper_len = self.redis_client.xlen("signals:paper")
                print(f"✅ signals:paper stream exists (length: {paper_len})")
            except:
                print(f"ℹ️  signals:paper stream does not exist yet (will be created on first write)")

            # Check if signals:live stream exists
            try:
                live_len = self.redis_client.xlen("signals:live")
                print(f"✅ signals:live stream exists (length: {live_len})")
            except:
                print(f"ℹ️  signals:live stream does not exist yet (will be created on first write)")

            # Check ACTIVE_SIGNALS alias
            active_signals = self.redis_client.get("ACTIVE_SIGNALS")
            if active_signals:
                active_signals_str = active_signals.decode() if isinstance(active_signals, bytes) else active_signals
                print(f"✅ ACTIVE_SIGNALS → {active_signals_str}")

                mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
                expected_stream = "signals:live" if mode.upper() == "LIVE" else "signals:paper"

                if active_signals_str != expected_stream:
                    self.warnings.append(
                        f"ACTIVE_SIGNALS ({active_signals_str}) does not match MODE ({mode})"
                    )
                    print(f"⚠️  ACTIVE_SIGNALS mismatch: expected {expected_stream} for MODE={mode}")
            else:
                self.warnings.append("ACTIVE_SIGNALS key not set in Redis")
                print("⚠️  ACTIVE_SIGNALS key not set in Redis")

        except Exception as e:
            self.errors.append(f"Stream configuration check failed: {str(e)}")
            print(f"❌ Error checking streams: {str(e)}")

    def check_config_alignment(self):
        """Check if all config files are aligned for live trading"""

        # Check settings.yaml
        settings_path = project_root / "config" / "settings.yaml"
        if settings_path.exists():
            try:
                with open(settings_path, "r") as f:
                    settings = yaml.safe_load(f)

                yaml_mode = settings.get("mode", "PAPER")
                print(f"✅ config/settings.yaml: mode={yaml_mode}")

                # Check Redis stream configuration
                redis_config = settings.get("redis", {})
                streams = redis_config.get("streams", {})

                signals_paper = streams.get("signals_paper", "")
                signals_live = streams.get("signals_live", "")

                if signals_paper == "signals:paper":
                    print(f"✅ settings.yaml: signals_paper={signals_paper}")
                else:
                    self.warnings.append(f"settings.yaml: signals_paper={signals_paper} (expected: signals:paper)")
                    print(f"⚠️  settings.yaml: signals_paper={signals_paper}")

                if signals_live == "signals:live":
                    print(f"✅ settings.yaml: signals_live={signals_live}")
                else:
                    self.warnings.append(f"settings.yaml: signals_live={signals_live} (expected: signals:live)")
                    print(f"⚠️  settings.yaml: signals_live={signals_live}")

            except Exception as e:
                self.warnings.append(f"Error reading settings.yaml: {str(e)}")
                print(f"⚠️  Error reading settings.yaml: {str(e)}")
        else:
            self.warnings.append("settings.yaml not found")
            print(f"⚠️  settings.yaml not found at: {settings_path}")

        # Check prod.yaml override
        prod_yaml = project_root / "config" / "overrides" / "prod.yaml"
        if prod_yaml.exists():
            try:
                with open(prod_yaml, "r") as f:
                    prod_config = yaml.safe_load(f)

                prod_mode = prod_config.get("mode", "")
                if prod_mode == "LIVE":
                    print(f"✅ config/overrides/prod.yaml: mode=LIVE")
                else:
                    self.warnings.append(f"prod.yaml mode is not LIVE: {prod_mode}")
                    print(f"⚠️  prod.yaml: mode={prod_mode} (expected: LIVE)")

            except Exception as e:
                self.warnings.append(f"Error reading prod.yaml: {str(e)}")
                print(f"⚠️  Error reading prod.yaml: {str(e)}")
        else:
            self.warnings.append("prod.yaml not found")
            print(f"⚠️  prod.yaml not found at: {prod_yaml}")

    def check_safety_gates(self):
        """Check if safety gates are properly configured"""

        print("Checking safety gate configuration...")

        # Check if risk config exists
        risk_config_path = project_root / "config" / "settings.yaml"
        if risk_config_path.exists():
            try:
                with open(risk_config_path, "r") as f:
                    settings = yaml.safe_load(f)

                risk = settings.get("risk", {})

                # Check drawdown limits
                day_max_dd = risk.get("day_max_drawdown_pct", 0)
                rolling_max_dd = risk.get("rolling_max_drawdown_pct", 0)

                if day_max_dd > 0:
                    print(f"✅ Daily max drawdown: {day_max_dd}%")
                else:
                    self.warnings.append("Daily max drawdown not configured")
                    print(f"⚠️  Daily max drawdown: {day_max_dd}%")

                if rolling_max_dd > 0:
                    print(f"✅ Rolling max drawdown: {rolling_max_dd}%")
                else:
                    self.warnings.append("Rolling max drawdown not configured")
                    print(f"⚠️  Rolling max drawdown: {rolling_max_dd}%")

                # Check position limits
                max_positions = risk.get("max_concurrent_positions", 0)
                if max_positions > 0:
                    print(f"✅ Max concurrent positions: {max_positions}")
                else:
                    self.warnings.append("Max concurrent positions not configured")
                    print(f"⚠️  Max concurrent positions: {max_positions}")

                # Check risk per trade
                risk_per_trade = risk.get("risk_per_trade_pct", 0)
                if risk_per_trade > 0:
                    print(f"✅ Risk per trade: {risk_per_trade}%")
                else:
                    self.warnings.append("Risk per trade not configured")
                    print(f"⚠️  Risk per trade: {risk_per_trade}%")

            except Exception as e:
                self.warnings.append(f"Error reading risk config: {str(e)}")
                print(f"⚠️  Error reading risk config: {str(e)}")

        # Check if safety gates module exists
        safety_gates_path = project_root / "protections" / "safety_gates.py"
        if safety_gates_path.exists():
            print(f"✅ Safety gates module found: {safety_gates_path.name}")
        else:
            self.warnings.append("safety_gates.py not found")
            print(f"⚠️  safety_gates.py not found at: {safety_gates_path}")

        # Check if risk manager exists
        risk_manager_path = project_root / "agents" / "risk_manager.py"
        if risk_manager_path.exists():
            print(f"✅ Risk manager module found: {risk_manager_path.name}")
        else:
            self.errors.append("risk_manager.py not found")
            print(f"❌ risk_manager.py not found at: {risk_manager_path}")

    def test_signal_write(self):
        """Test writing a signal to verify stream routing"""

        if not self.redis_client:
            self.warnings.append("Redis not connected, skipping signal write test")
            print("⚠️  Redis not connected, skipping signal write test")
            return

        try:
            mode = os.getenv("MODE") or os.getenv("TRADING_MODE") or os.getenv("BOT_MODE", "PAPER")
            stream_key = f"signals:{mode.lower()}"

            # Create test signal
            test_signal = {
                "id": "test_validation_signal",
                "ts": "1730000000000",
                "pair": "BTC-USD",
                "side": "long",
                "entry": "50000.0",
                "sl": "49000.0",
                "tp": "52000.0",
                "strategy": "validation_test",
                "confidence": "0.99",
                "mode": mode.lower(),
                "note": "Validation test signal - safe to ignore"
            }

            # Write to stream
            entry_id = self.redis_client.xadd(stream_key, test_signal, maxlen=10000, approximate=True)
            print(f"✅ Test signal written to {stream_key}")
            print(f"   Entry ID: {entry_id}")

            # Verify we can read it back
            signals = self.redis_client.xrevrange(stream_key, count=1)
            if signals:
                latest_entry_id, fields = signals[0]
                if fields.get("id") == "test_validation_signal":
                    print(f"✅ Test signal verified in {stream_key}")
                else:
                    self.warnings.append("Could not verify test signal")
                    print(f"⚠️  Could not verify test signal")

        except Exception as e:
            self.errors.append(f"Signal write test failed: {str(e)}")
            print(f"❌ Signal write test failed: {str(e)}")

    def print_summary(self):
        """Print validation summary"""

        print("\n" + "="*80)
        print("VALIDATION SUMMARY")
        print("="*80 + "\n")

        if self.errors:
            print(f"[X] ERRORS ({len(self.errors)}):")
            for i, error in enumerate(self.errors, 1):
                print(f"   {i}. {error}")
            print()

        if self.warnings:
            print(f"[!] WARNINGS ({len(self.warnings)}):")
            for i, warning in enumerate(self.warnings, 1):
                print(f"   {i}. {warning}")
            print()

        if not self.errors and not self.warnings:
            print("[OK] ALL CHECKS PASSED - SYSTEM READY FOR LIVE TRADING")
            print("\n[!] IMPORTANT: Before going live:")
            print("   1. Review all configuration files")
            print("   2. Ensure LIVE_TRADING_CONFIRMATION is set")
            print("   3. Start with small position sizes")
            print("   4. Monitor closely for the first hour")
            print("   5. Have emergency stop procedure ready")
        elif not self.errors:
            print("[OK] NO CRITICAL ERRORS - System operational but has warnings")
            print("   Review warnings above before proceeding")
        else:
            print("[X] CRITICAL ERRORS FOUND - DO NOT START LIVE TRADING")
            print("   Fix errors above before proceeding")

        print("\n" + "="*80 + "\n")


def main():
    """Main entry point"""

    validator = LiveTradingValidator()
    success = validator.run_all_checks()

    # Cleanup
    if validator.redis_client:
        validator.redis_client.close()

    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
