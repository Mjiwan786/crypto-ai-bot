"""
PRD-001 Compliant Kraken Configuration Loader

Loads trading pairs and timeframes from kraken_ohlcv.yaml and kraken.yaml
to ensure all configured pairs/timeframes are actually subscribed.

This module provides configuration loading for:
- Trading pairs (tier_1, tier_2, tier_3 from kraken_ohlcv.yaml)
- Timeframes (primary and synthetic from kraken_ohlcv.yaml)
- Stream naming (matches kraken_ohlcv.yaml exactly)

IMPORTANT: For the canonical trading pairs list, see config/trading_pairs.py
which is the single source of truth for all supported pairs.
"""

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Set

import yaml

# Import canonical trading pairs module
from config.trading_pairs import (
    get_pair_symbols,
    get_kraken_symbols,
    symbol_to_kraken,
    get_enabled_pairs,
    ENABLED_PAIR_SYMBOLS,
)

logger = logging.getLogger(__name__)


class KrakenConfigLoader:
    """
    Loads and validates Kraken configuration from YAML files.
    
    PRD-001 Compliance:
    - Loads pairs from kraken_ohlcv.yaml (tier_1, tier_2, tier_3)
    - Loads timeframes from kraken_ohlcv.yaml (primary, synthetic)
    - Validates stream naming matches kraken_ohlcv.yaml
    - Provides unified interface for WS client and OHLCV manager
    """

    def __init__(
        self,
        kraken_ohlcv_path: Optional[str] = None,
        kraken_path: Optional[str] = None,
    ):
        """
        Initialize configuration loader.

        Args:
            kraken_ohlcv_path: Path to kraken_ohlcv.yaml (auto-discovered if None)
            kraken_path: Path to kraken.yaml (auto-discovered if None)
        """
        self.kraken_ohlcv_path = kraken_ohlcv_path or self._find_kraken_ohlcv_config()
        self.kraken_path = kraken_path or self._find_kraken_config()

        # Loaded configuration
        self.ohlcv_config: Dict = {}
        self.kraken_config: Dict = {}

        # Cached results
        self._pairs: Optional[List[str]] = None
        self._kraken_pairs: Optional[List[str]] = None
        self._timeframes: Optional[List[str]] = None
        self._native_timeframes: Optional[List[str]] = None
        self._synthetic_timeframes: Optional[List[str]] = None

        # Load configuration
        self._load_config()

    def _find_kraken_ohlcv_config(self) -> str:
        """Find kraken_ohlcv.yaml configuration file"""
        possible_paths = [
            "config/exchange_configs/kraken_ohlcv.yaml",
            "config/kraken_ohlcv.yaml",
            "../config/exchange_configs/kraken_ohlcv.yaml",
        ]

        for path in possible_paths:
            if Path(path).exists():
                return path

        logger.warning("kraken_ohlcv.yaml not found, using defaults")
        return "config/exchange_configs/kraken_ohlcv.yaml"

    def _find_kraken_config(self) -> str:
        """Find kraken.yaml configuration file"""
        possible_paths = [
            "config/exchange_configs/kraken.yaml",
            "config/kraken.yaml",
            "../config/exchange_configs/kraken.yaml",
        ]

        for path in possible_paths:
            if Path(path).exists():
                return path

        logger.warning("kraken.yaml not found, using defaults")
        return "config/exchange_configs/kraken.yaml"

    def _load_config(self) -> None:
        """Load configuration from YAML files"""
        # Load kraken_ohlcv.yaml
        if Path(self.kraken_ohlcv_path).exists():
            try:
                with open(self.kraken_ohlcv_path, 'r') as f:
                    self.ohlcv_config = yaml.safe_load(f) or {}
                logger.info(f"Loaded OHLCV config from {self.kraken_ohlcv_path}")
            except Exception as e:
                logger.error(f"Error loading OHLCV config: {e}")
                self.ohlcv_config = {}
        else:
            logger.warning(f"OHLCV config not found at {self.kraken_ohlcv_path}")
            self.ohlcv_config = {}

        # Load kraken.yaml
        if Path(self.kraken_path).exists():
            try:
                with open(self.kraken_path, 'r') as f:
                    self.kraken_config = yaml.safe_load(f) or {}
                logger.info(f"Loaded Kraken config from {self.kraken_path}")
            except Exception as e:
                logger.error(f"Error loading Kraken config: {e}")
                self.kraken_config = {}
        else:
            logger.warning(f"Kraken config not found at {self.kraken_path}")
            self.kraken_config = {}

    def get_all_pairs(self, include_disabled: bool = False) -> List[str]:
        """
        Get all trading pairs from kraken_ohlcv.yaml.

        Args:
            include_disabled: If True, include pairs marked as enabled=false

        Returns:
            List of pairs in format "BTC/USD", "ETH/USD", etc.
        """
        if self._pairs is not None and not include_disabled:
            return self._pairs

        pairs = []
        trading_pairs = self.ohlcv_config.get("trading_pairs", {})

        # Load from tier_1, tier_2, tier_3
        for tier_name in ["tier_1", "tier_2", "tier_3"]:
            tier_pairs = trading_pairs.get(tier_name, [])
            for pair_data in tier_pairs:
                if isinstance(pair_data, dict):
                    symbol = pair_data.get("symbol", "")
                    # Check if pair is enabled (default to True if not specified)
                    enabled = pair_data.get("enabled", True)
                    if not include_disabled and not enabled:
                        logger.debug(f"Skipping disabled pair: {symbol}")
                        continue
                else:
                    symbol = str(pair_data)

                if symbol and symbol not in pairs:
                    pairs.append(symbol)

        # Fallback to canonical trading pairs module if config not found
        if not pairs:
            logger.warning("No pairs found in YAML config, using canonical trading_pairs module")
            pairs = ENABLED_PAIR_SYMBOLS.copy()

        if not include_disabled:
            self._pairs = sorted(pairs)
        logger.info(f"Loaded {len(pairs)} trading pairs: {', '.join(pairs)}")
        return sorted(pairs)

    def get_kraken_pairs(self) -> List[str]:
        """
        Get pairs in Kraken format (XBTUSD, ETHUSD, etc.) for WebSocket subscription.

        Returns:
            List of Kraken-formatted pairs
        """
        if self._kraken_pairs is not None:
            return self._kraken_pairs

        # Symbol mapping from kraken.yaml
        normalize_map = self.kraken_config.get("symbols", {}).get("normalize", {})
        denormalize_map = self.kraken_config.get("symbols", {}).get("denormalize", {})

        kraken_pairs = []
        for pair in self.get_all_pairs():
            # Try normalize map first
            kraken_pair = normalize_map.get(pair)
            if not kraken_pair:
                # Try reverse lookup in denormalize map
                for k, v in denormalize_map.items():
                    if v == pair:
                        kraken_pair = k
                        break

            # Fallback: use canonical trading_pairs module for mapping
            if not kraken_pair:
                kraken_pair = symbol_to_kraken(pair)
                if not kraken_pair:
                    # Last resort: remove / and convert to uppercase
                    kraken_pair = pair.replace("/", "").upper()

            if kraken_pair and kraken_pair not in kraken_pairs:
                kraken_pairs.append(kraken_pair)

        self._kraken_pairs = kraken_pairs
        logger.info(f"Converted to {len(self._kraken_pairs)} Kraken pairs: {', '.join(self._kraken_pairs)}")
        return self._kraken_pairs

    def get_all_timeframes(self) -> List[str]:
        """
        Get all enabled timeframes from kraken_ohlcv.yaml.

        Returns:
            List of timeframe strings (e.g., ["1m", "5m", "15s", "30s"])
        """
        if self._timeframes is not None:
            return self._timeframes

        timeframes = set()
        timeframes_config = self.ohlcv_config.get("timeframes", {})

        # Load primary (native) timeframes
        primary = timeframes_config.get("primary", {})
        if isinstance(primary, dict):
            for tf_name in primary.keys():
                timeframes.add(tf_name)
        elif isinstance(primary, list):
            for tf in primary:
                if isinstance(tf, dict):
                    timeframes.add(tf.get("name", ""))
                else:
                    timeframes.add(str(tf))

        # Load synthetic timeframes
        synthetic = timeframes_config.get("synthetic", {})
        if isinstance(synthetic, dict):
            for tf_name in synthetic.keys():
                # Check feature flag for 5s bars
                if tf_name == "5s":
                    tf_config = synthetic.get(tf_name, {})
                    feature_flag = tf_config.get("feature_flag", "")
                    if feature_flag:
                        # Parse env var (e.g., "${ENABLE_5S_BARS:false}")
                        env_var = feature_flag.replace("${", "").replace("}", "").split(":")[0]
                        if env_var:
                            enabled = os.getenv(env_var, "false").lower() == "true"
                            if not enabled:
                                logger.info(f"Skipping 5s timeframe (feature flag {env_var} not enabled)")
                                continue
                timeframes.add(tf_name)
        elif isinstance(synthetic, list):
            for tf in synthetic:
                if isinstance(tf, dict):
                    timeframes.add(tf.get("name", ""))
                else:
                    timeframes.add(str(tf))

        # Fallback to defaults if config not found
        if not timeframes:
            logger.warning("No timeframes found in config, using defaults")
            timeframes = {"1m", "5m", "15m", "1h", "15s", "30s"}

        self._timeframes = sorted(list(timeframes))
        logger.info(f"Loaded {len(self._timeframes)} timeframes: {', '.join(self._timeframes)}")
        return self._timeframes

    def get_native_timeframes(self) -> List[str]:
        """
        Get native (Kraken API) timeframes only.

        Returns:
            List of native timeframe strings (e.g., ["1m", "5m", "15m"])
        """
        if self._native_timeframes is not None:
            return self._native_timeframes

        timeframes_config = self.ohlcv_config.get("timeframes", {})
        primary = timeframes_config.get("primary", {})

        native = []
        if isinstance(primary, dict):
            native = list(primary.keys())
        elif isinstance(primary, list):
            for tf in primary:
                if isinstance(tf, dict):
                    native.append(tf.get("name", ""))
                else:
                    native.append(str(tf))

        # Fallback
        if not native:
            native = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

        self._native_timeframes = sorted(native)
        return self._native_timeframes

    def get_synthetic_timeframes(self) -> List[str]:
        """
        Get synthetic (derived from trades) timeframes only.

        Returns:
            List of synthetic timeframe strings (e.g., ["5s", "15s", "30s"])
        """
        if self._synthetic_timeframes is not None:
            return self._synthetic_timeframes

        timeframes_config = self.ohlcv_config.get("timeframes", {})
        synthetic = timeframes_config.get("synthetic", {})

        synthetic_tfs = []
        if isinstance(synthetic, dict):
            for tf_name in synthetic.keys():
                # Check feature flag for 5s bars
                if tf_name == "5s":
                    tf_config = synthetic.get(tf_name, {})
                    feature_flag = tf_config.get("feature_flag", "")
                    if feature_flag:
                        env_var = feature_flag.replace("${", "").replace("}", "").split(":")[0]
                        if env_var:
                            enabled = os.getenv(env_var, "false").lower() == "true"
                            if not enabled:
                                continue
                synthetic_tfs.append(tf_name)
        elif isinstance(synthetic, list):
            for tf in synthetic:
                if isinstance(tf, dict):
                    synthetic_tfs.append(tf.get("name", ""))
                else:
                    synthetic_tfs.append(str(tf))

        # Fallback
        if not synthetic_tfs:
            synthetic_tfs = ["15s", "30s"]

        self._synthetic_timeframes = sorted(synthetic_tfs)
        return self._synthetic_timeframes

    def get_kraken_ohlc_intervals(self) -> List[int]:
        """
        Get Kraken OHLC intervals (in minutes) to subscribe to.

        Returns:
            List of intervals (e.g., [1, 5, 15, 60])
        """
        intervals = []
        timeframes_config = self.ohlcv_config.get("timeframes", {})
        primary = timeframes_config.get("primary", {})

        # Map timeframe to Kraken interval
        tf_to_interval = {
            "1m": 1,
            "5m": 5,
            "15m": 15,
            "30m": 30,
            "1h": 60,
            "4h": 240,
            "1d": 1440,
        }

        if isinstance(primary, dict):
            for tf_name, tf_config in primary.items():
                if isinstance(tf_config, dict):
                    interval = tf_config.get("kraken_interval")
                    if interval:
                        intervals.append(interval)
                elif tf_name in tf_to_interval:
                    intervals.append(tf_to_interval[tf_name])
        elif isinstance(primary, list):
            for tf in primary:
                if isinstance(tf, dict):
                    interval = tf.get("kraken_interval")
                    if interval:
                        intervals.append(interval)
                    else:
                        tf_name = tf.get("name", "")
                        if tf_name in tf_to_interval:
                            intervals.append(tf_to_interval[tf_name])

        # Fallback
        if not intervals:
            intervals = [1, 5, 15, 30, 60, 240, 1440]

        return sorted(set(intervals))

    def get_stream_name(self, timeframe: str, pair: str) -> str:
        """
        Get Redis stream name for OHLCV data.

        PRD-001 Section 2.2: kraken:ohlc:<tf>:<pair>
        Example: kraken:ohlc:1m:BTC-USD

        Args:
            timeframe: Timeframe (e.g., "1m", "15s")
            pair: Trading pair (e.g., "BTC/USD")

        Returns:
            Stream name (e.g., "kraken:ohlc:1m:BTC-USD")
        """
        # Get stream prefix from config
        streams_config = self.ohlcv_config.get("streams", {})
        redis_config = streams_config.get("redis", {})
        stream_prefix = redis_config.get("stream_prefix", "kraken:ohlc")

        # Normalize pair (BTC/USD -> BTC-USD)
        pair_normalized = pair.replace("/", "-")

        return f"{stream_prefix}:{timeframe}:{pair_normalized}"

    def get_pairs_by_tier(self, tier: str) -> List[str]:
        """
        Get pairs for a specific tier.

        Args:
            tier: Tier name ("tier_1", "tier_2", "tier_3")

        Returns:
            List of pairs in that tier
        """
        trading_pairs = self.ohlcv_config.get("trading_pairs", {})
        tier_pairs = trading_pairs.get(tier, [])

        pairs = []
        for pair_data in tier_pairs:
            if isinstance(pair_data, dict):
                symbol = pair_data.get("symbol", "")
            else:
                symbol = str(pair_data)

            if symbol:
                pairs.append(symbol)

        return pairs

    def validate_config(self) -> Dict[str, bool]:
        """
        Validate configuration completeness.

        Returns:
            Dict with validation results
        """
        results = {
            "pairs_loaded": len(self.get_all_pairs()) > 0,
            "timeframes_loaded": len(self.get_all_timeframes()) > 0,
            "native_timeframes_loaded": len(self.get_native_timeframes()) > 0,
            "synthetic_timeframes_loaded": len(self.get_synthetic_timeframes()) > 0,
            "kraken_pairs_loaded": len(self.get_kraken_pairs()) > 0,
        }

        return results


# Singleton instance
_config_loader: Optional[KrakenConfigLoader] = None


def get_kraken_config_loader() -> KrakenConfigLoader:
    """Get singleton configuration loader instance"""
    global _config_loader
    if _config_loader is None:
        _config_loader = KrakenConfigLoader()
    return _config_loader









