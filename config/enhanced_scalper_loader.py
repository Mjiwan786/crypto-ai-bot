"""
Enhanced Scalper Configuration Loader

Loads and validates configuration for the enhanced scalper agent with
multi-strategy integration.
"""

import os
import yaml
import logging
from typing import Any, Dict, Optional
from pathlib import Path


class EnhancedScalperConfigLoader:
    """
    Configuration loader for enhanced scalper agent
    
    Handles loading, validation, and merging of configuration files
    with environment variable overrides.
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration loader
        
        Args:
            config_path: Path to configuration file (optional)
        """
        self.config_path = config_path or self._find_config_file()
        self.logger = logging.getLogger(__name__)
        
    def _find_config_file(self) -> str:
        """Find the configuration file in standard locations"""
        possible_paths = [
            "config/enhanced_scalper_config.yaml",
            "enhanced_scalper_config.yaml",
            "config/scalper_config.yaml",
            "scalper_config.yaml"
        ]
        
        for path in possible_paths:
            if os.path.exists(path):
                return path
        
        # Default fallback
        return "config/enhanced_scalper_config.yaml"
    
    def load_config(self) -> Dict[str, Any]:
        """
        Load configuration from file and environment variables
        
        Returns:
            Merged configuration dictionary
        """
        try:
            # Load base configuration from file
            base_config = self._load_file_config()
            
            # Apply environment variable overrides
            env_config = self._load_env_config()
            
            # Merge configurations
            merged_config = self._merge_configs(base_config, env_config)
            
            # Validate configuration
            self._validate_config(merged_config)
            
            self.logger.info("Enhanced scalper configuration loaded successfully")
            return merged_config
            
        except Exception as e:
            self.logger.error(f"Error loading configuration: {e}")
            raise
    
    def _load_file_config(self) -> Dict[str, Any]:
        """Load configuration from YAML file"""
        try:
            if not os.path.exists(self.config_path):
                self.logger.warning(f"Configuration file not found: {self.config_path}")
                return self._get_default_config()
            
            with open(self.config_path, 'r') as file:
                config = yaml.safe_load(file)
            
            self.logger.info(f"Loaded configuration from {self.config_path}")
            return config or {}
            
        except Exception as e:
            self.logger.error(f"Error loading configuration file: {e}")
            return self._get_default_config()
    
    def _load_env_config(self) -> Dict[str, Any]:
        """Load configuration from environment variables"""
        env_config = {}
        
        # Scalper configuration
        if os.getenv('SCALPER_PAIRS'):
            env_config['scalper'] = env_config.get('scalper', {})
            env_config['scalper']['pairs'] = os.getenv('SCALPER_PAIRS').split(',')
        
        if os.getenv('SCALPER_TARGET_BPS'):
            env_config['scalper'] = env_config.get('scalper', {})
            env_config['scalper']['target_bps'] = int(os.getenv('SCALPER_TARGET_BPS'))
        
        if os.getenv('SCALPER_STOP_LOSS_BPS'):
            env_config['scalper'] = env_config.get('scalper', {})
            env_config['scalper']['stop_loss_bps'] = int(os.getenv('SCALPER_STOP_LOSS_BPS'))
        
        # Redis configuration
        if os.getenv('REDIS_HOST'):
            env_config['redis'] = env_config.get('redis', {})
            env_config['redis']['host'] = os.getenv('REDIS_HOST')
        
        if os.getenv('REDIS_PORT'):
            env_config['redis'] = env_config.get('redis', {})
            env_config['redis']['port'] = int(os.getenv('REDIS_PORT'))
        
        # AI Engine configuration
        if os.getenv('AI_ENGINE_MODE'):
            env_config['ai_engine'] = env_config.get('ai_engine', {})
            env_config['ai_engine']['mode'] = os.getenv('AI_ENGINE_MODE')
        
        # Signal filtering configuration
        if os.getenv('MIN_ALIGNMENT_CONFIDENCE'):
            env_config['signal_filtering'] = env_config.get('signal_filtering', {})
            env_config['signal_filtering']['min_alignment_confidence'] = float(os.getenv('MIN_ALIGNMENT_CONFIDENCE'))
        
        if os.getenv('REQUIRE_ALIGNMENT'):
            env_config['signal_filtering'] = env_config.get('signal_filtering', {})
            env_config['signal_filtering']['require_alignment'] = os.getenv('REQUIRE_ALIGNMENT').lower() == 'true'
        
        return env_config
    
    def _merge_configs(self, base_config: Dict[str, Any], env_config: Dict[str, Any]) -> Dict[str, Any]:
        """Merge base configuration with environment overrides"""
        merged = base_config.copy()
        
        def deep_merge(base: Dict, override: Dict) -> Dict:
            for key, value in override.items():
                if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                    base[key] = deep_merge(base[key], value)
                else:
                    base[key] = value
            return base
        
        return deep_merge(merged, env_config)
    
    def _validate_config(self, config: Dict[str, Any]) -> None:
        """Validate configuration parameters"""
        
        # Validate scalper configuration
        scalper_config = config.get('scalper', {})
        if not scalper_config.get('pairs'):
            raise ValueError("Scalper pairs must be specified")
        
        if scalper_config.get('target_bps', 0) <= 0:
            raise ValueError("Target BPS must be positive")
        
        if scalper_config.get('stop_loss_bps', 0) <= 0:
            raise ValueError("Stop loss BPS must be positive")
        
        # Validate strategy router configuration
        router_config = config.get('strategy_router', {})
        allocations = router_config.get('strategy_allocations', {})
        total_allocation = sum(allocations.values())
        if total_allocation > 1.0:
            raise ValueError(f"Strategy allocations sum ({total_allocation}) exceeds 1.0")
        
        # Validate signal filtering configuration
        filter_config = config.get('signal_filtering', {})
        min_confidence = filter_config.get('min_alignment_confidence', 0)
        if not 0 <= min_confidence <= 1:
            raise ValueError("Min alignment confidence must be between 0 and 1")
        
        # Validate regime adaptation configuration
        regime_config = config.get('regime_adaptation', {})
        for regime in ['sideways', 'bull', 'bear']:
            target_bps = regime_config.get(f'{regime}_target_bps', 0)
            if target_bps <= 0:
                raise ValueError(f"{regime} target BPS must be positive")
        
        self.logger.info("Configuration validation passed")
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration as fallback"""
        return {
            'scalper': {
                'pairs': ['BTC/USD', 'ETH/USD'],
                'target_bps': 10,
                'stop_loss_bps': 5,
                'timeframe': '15s',
                'preferred_order_type': 'limit',
                'post_only': True,
                'hidden_orders': False,
                'max_slippage_bps': 4,
                'max_trades_per_minute': 4,
                'cooldown_after_loss_seconds': 90,
                'daily_trade_limit': 150,
                'max_hold_seconds': 120,
                'max_spread_bps': 3.0,
                'min_liquidity_usd': 1000000.0
            },
            'strategy_router': {
                'strategy_allocations': {
                    'breakout': 0.25,
                    'mean_reversion': 0.20,
                    'momentum': 0.25,
                    'trend_following': 0.30,
                    'sideways': 0.15
                },
                'min_confidence': 0.3,
                'high_confidence': 0.7
            },
            'signal_filtering': {
                'min_alignment_confidence': 0.3,
                'min_strategy_alignment': 0.6,
                'require_alignment': False,
                'min_regime_confidence': 0.3,
                'min_scalping_confidence': 0.5
            },
            'enhanced_validation': {
                'min_enhanced_confidence': 0.6,
                'min_regime_confidence': 0.4,
                'require_strategy_alignment': False
            },
            'regime_adaptation': {
                'sideways_target_bps': 8,
                'sideways_stop_bps': 4,
                'sideways_max_trades': 6,
                'bull_target_bps': 12,
                'bull_stop_bps': 6,
                'bull_max_trades': 4,
                'bear_target_bps': 12,
                'bear_stop_bps': 6,
                'bear_max_trades': 4
            },
            'ai_engine': {
                'mode': 'hypergrowth',
                'daily_profit_target': 0.015,
                'max_daily_loss': -0.03,
                'regime_detection': {
                    'enabled': True,
                    'update_interval_seconds': 300,
                    'confidence_threshold': 0.4
                }
            },
            'redis': {
                'enabled': True,
                'host': 'localhost',
                'port': 6379,
                'db': 0,
                'password': None
            },
            'logging': {
                'level': 'INFO',
                'format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                'file': 'logs/enhanced_scalper.log',
                'max_size': '10MB',
                'backup_count': 5
            }
        }
    
    def save_config(self, config: Dict[str, Any], output_path: Optional[str] = None) -> None:
        """
        Save configuration to file
        
        Args:
            config: Configuration dictionary
            output_path: Output file path (optional)
        """
        output_path = output_path or self.config_path
        
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            
            with open(output_path, 'w') as file:
                yaml.dump(config, file, default_flow_style=False, indent=2)
            
            self.logger.info(f"Configuration saved to {output_path}")
            
        except Exception as e:
            self.logger.error(f"Error saving configuration: {e}")
            raise


def load_enhanced_scalper_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Convenience function to load enhanced scalper configuration
    
    Args:
        config_path: Path to configuration file (optional)
        
    Returns:
        Configuration dictionary
    """
    loader = EnhancedScalperConfigLoader(config_path)
    return loader.load_config()


if __name__ == "__main__":
    # Test configuration loading
    import logging
    
    logging.basicConfig(level=logging.INFO)
    
    try:
        config = load_enhanced_scalper_config()
        print("Configuration loaded successfully:")
        print(f"Scalper pairs: {config['scalper']['pairs']}")
        print(f"Target BPS: {config['scalper']['target_bps']}")
        print(f"Strategy allocations: {config['strategy_router']['strategy_allocations']}")
        print(f"Signal filtering enabled: {config['signal_filtering']['require_alignment']}")
        
    except Exception as e:
        print(f"Error loading configuration: {e}")

