"""
Regime-Based Strategy Router for Autonomous Crypto AI Trading System
Dynamically routes market data to appropriate strategies based on detected market regimes.
"""

import pandas as pd
import importlib
import logging
from typing import Dict, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

# Imports for strategy modules and context
try:
    from utils.logger import get_logger
except ImportError:
    import logging
    def get_logger(name):
        return logging.getLogger(name)

try:
    from mcp.context import MarketContext
except ImportError:
    # Create a mock MarketContext for testing when MCP is not available
    class MarketContext:
        def __init__(self, regime_state="bull", **kwargs):
            self.regime_state = regime_state
            for key, value in kwargs.items():
                setattr(self, key, value)


class MarketRegime(Enum):
    """Enumeration of possible market regimes"""
    BULL = "bull"
    BEAR = "bear" 
    SIDEWAYS = "sideways"
    UNKNOWN = "unknown"


@dataclass
class StrategyResult:
    """Standardized strategy result structure"""
    signal: str  # buy, sell, hold
    confidence: float  # 0.0 - 1.0
    position_size: float  # 0.0 - 1.0
    metadata: Dict[str, Any]


class RegimeRouter:
    """
    Main router class that selects and executes strategies based on market regime.
    Implements lazy loading and intelligent strategy selection with fallback mechanisms.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the regime router with configuration.
        
        Args:
            config: Configuration dictionary containing strategy allocations and thresholds
        """
        self.config = config
        self.logger = get_logger(__name__)
        self._strategy_cache = {}  # Cache for loaded strategy modules
        
        # Strategy preferences by regime
        self.regime_preferences = {
            MarketRegime.BULL: ["momentum", "trend_following"],
            MarketRegime.BEAR: ["mean_reversion", "breakout"],
            MarketRegime.SIDEWAYS: ["sideways"]
        }
        
        # Minimum confidence thresholds
        self.min_confidence = 0.3
        self.high_confidence = 0.7
        
        self.logger.info(f"RegimeRouter initialized with {len(self.regime_preferences)} regime strategies")
    
    def _load_strategy(self, strategy_name: str):
        """
        Lazy load strategy module and cache it.
        
        Args:
            strategy_name: Name of the strategy module to load
            
        Returns:
            Strategy module with execute method
        """
        if strategy_name not in self._strategy_cache:
            try:
                module_path = f"strategies.{strategy_name}"
                strategy_module = importlib.import_module(module_path)
                self._strategy_cache[strategy_name] = strategy_module
                self.logger.debug(f"Loaded strategy module: {strategy_name}")
            except ImportError as e:
                self.logger.error(f"Failed to load strategy {strategy_name}: {e}")
                return None
        
        return self._strategy_cache[strategy_name]
    
    def _get_regime_from_context(self, context: MarketContext) -> MarketRegime:
        """
        Extract current market regime from MCP context.
        
        Args:
            context: Market context containing regime state
            
        Returns:
            Current market regime
        """
        try:
            regime_state = getattr(context, 'regime_state', 'unknown').lower()
            return MarketRegime(regime_state)
        except (ValueError, AttributeError):
            self.logger.warning(f"Invalid regime state: {getattr(context, 'regime_state', 'None')}")
            return MarketRegime.UNKNOWN
    
    def _select_strategy(self, regime: MarketRegime) -> Tuple[str, str]:
        """
        Select the best strategy for the given regime based on allocations.
        
        Args:
            regime: Current market regime
            
        Returns:
            Tuple of (strategy_name, selection_reason)
        """
        preferred_strategies = self.regime_preferences.get(regime, [])
        
        if not preferred_strategies:
            return "trend_following", f"No preferred strategies for regime {regime.value}, using default"
        
        # Get strategy allocations from config
        allocations = self.config.get("strategy_allocations", {})
        
        # Select strategy with highest allocation among preferred ones
        best_strategy = None
        best_allocation = 0.0
        
        for strategy in preferred_strategies:
            allocation = allocations.get(strategy, 0.0)
            if allocation > best_allocation:
                best_allocation = allocation
                best_strategy = strategy
        
        if best_strategy:
            reason = f"Regime = {regime.value}, selected {best_strategy} (allocation: {best_allocation})"
            return best_strategy, reason
        else:
            # Fallback to first preferred strategy
            fallback = preferred_strategies[0]
            reason = f"Regime = {regime.value}, using fallback {fallback}"
            return fallback, reason
    
    def _execute_strategy(self, strategy_name: str, df: pd.DataFrame, context: MarketContext, config: dict) -> Optional[StrategyResult]:
        """
        Execute a specific strategy and return normalized results.
        
        Args:
            strategy_name: Name of strategy to execute
            df: Market data DataFrame
            context: Market context
            config: Configuration dictionary
            
        Returns:
            StrategyResult or None if execution fails
        """
        strategy_module = self._load_strategy(strategy_name)
        if not strategy_module:
            return None
        
        try:
            # Most strategies should have an execute function
            if hasattr(strategy_module, 'execute'):
                result = strategy_module.execute(df, context, config)
            elif hasattr(strategy_module, 'analyze'):
                result = strategy_module.analyze(df, context, config)
            else:
                self.logger.error(f"Strategy {strategy_name} missing execute/analyze method")
                return None
            
            # Normalize result format
            if isinstance(result, dict):
                return StrategyResult(
                    signal=result.get('signal', 'hold'),
                    confidence=result.get('confidence', 0.5),
                    position_size=result.get('position_size', 0.1),
                    metadata=result.get('metadata', {})
                )
            else:
                self.logger.warning(f"Unexpected result format from {strategy_name}: {type(result)}")
                return None
                
        except Exception as e:
            self.logger.error(f"Strategy {strategy_name} execution failed: {e}")
            return None
    
    def _create_fallback_signal(self, regime: MarketRegime, reason: str) -> Dict[str, Any]:
        """
        Create a conservative fallback signal when no strategy provides confident results.
        
        Args:
            regime: Current market regime
            reason: Reason for fallback
            
        Returns:
            Fallback signal dictionary
        """
        return {
            "strategy_used": "fallback",
            "signal": "hold",
            "confidence": 0.1,
            "position_size": 0.0,
            "regime_state": regime.value,
            "reason": f"Fallback triggered: {reason}",
            "metadata": {
                "fallback": True,
                "original_regime": regime.value
            }
        }
    
    def route(self, df: pd.DataFrame, context: MarketContext, config: dict) -> Dict[str, Any]:
        """
        Main routing function that selects and executes the appropriate strategy.
        
        Args:
            df: Market data DataFrame with OHLCV data
            context: MarketContext containing regime state and other market info
            config: Configuration dictionary with strategy settings
            
        Returns:
            Normalized signal dictionary with strategy results
        """
        # Get current market regime
        regime = self._get_regime_from_context(context)
        
        self.logger.info(f"Routing decision for regime: {regime.value}")
        
        # Select primary strategy
        primary_strategy, selection_reason = self._select_strategy(regime)
        
        # Execute primary strategy
        result = self._execute_strategy(primary_strategy, df, context, config)
        
        if result and result.confidence >= self.min_confidence:
            # Primary strategy succeeded
            signal_dict = {
                "strategy_used": primary_strategy,
                "signal": result.signal,
                "confidence": result.confidence,
                "position_size": result.position_size,
                "regime_state": regime.value,
                "reason": selection_reason,
                "metadata": result.metadata
            }
            
            self.logger.info(f"Primary strategy {primary_strategy} executed successfully "
                           f"(signal: {result.signal}, confidence: {result.confidence:.2f})")
            
            return signal_dict
        
        # Primary strategy failed or low confidence - try backup strategies
        backup_strategies = []
        all_strategies = ["trend_following", "breakout", "momentum", "mean_reversion", "sideways"]
        
        # Get backup strategies (exclude primary)
        for strategy in all_strategies:
            if strategy != primary_strategy:
                backup_strategies.append(strategy)
        
        self.logger.warning(f"Primary strategy {primary_strategy} failed or low confidence, trying backups")
        
        # Try backup strategies
        for backup_strategy in backup_strategies[:2]:  # Try up to 2 backups
            backup_result = self._execute_strategy(backup_strategy, df, context, config)
            
            if backup_result and backup_result.confidence >= self.min_confidence:
                signal_dict = {
                    "strategy_used": backup_strategy,
                    "signal": backup_result.signal,
                    "confidence": backup_result.confidence,
                    "position_size": backup_result.position_size,
                    "regime_state": regime.value,
                    "reason": (
                        f"Backup strategy: primary {primary_strategy} failed, "
                        f"using {backup_strategy}"
                    ),
                    "metadata": {**backup_result.metadata, "backup_used": True}
                }
                
                self.logger.info(
                    f"Backup strategy {backup_strategy} succeeded "
                    f"(signal: {backup_result.signal}, confidence: {backup_result.confidence:.2f})"
                )
                
                return signal_dict
        
        # All strategies failed - return fallback
        fallback_reason = f"All strategies failed for regime {regime.value}"
        fallback_signal = self._create_fallback_signal(regime, fallback_reason)
        
        self.logger.warning(f"Routing fallback triggered: {fallback_reason}")
        
        return fallback_signal
    
    def get_strategy_health(self) -> Dict[str, Any]:
        """
        Return health status of all loaded strategies.
        
        Returns:
            Dictionary with strategy health metrics
        """
        health_status = {
            "loaded_strategies": list(self._strategy_cache.keys()),
            "total_cached": len(self._strategy_cache),
            "regime_preferences": {k.value: v for k, v in self.regime_preferences.items()}
        }
        
        return health_status


# Convenience function for direct usage
def route_strategy(df: pd.DataFrame, context: MarketContext, config: dict) -> Dict[str, Any]:
    """
    Convenience function to create router and execute routing in one call.
    
    Args:
        df: Market data DataFrame
        context: Market context
        config: Configuration dictionary
        
    Returns:
        Strategy routing result
    """
    router = RegimeRouter(config)
    return router.route(df, context, config)


# Example usage and testing
if __name__ == "__main__":
    # Example configuration for testing
    test_config = {
        "strategy_allocations": {
            "trend_following": 0.25,
            "breakout": 0.20,
            "mean_reversion": 0.15,
            "momentum": 0.25,
            "sideways": 0.15
        },
        "ai_engine": {
            "mode": "hypergrowth",
            "daily_profit_target": 0.015,
            "max_daily_loss": -0.03
        }
    }
    
    # Create mock context for testing
    class MockContext:
        def __init__(self, regime_state="bull"):
            self.regime_state = regime_state
    
    # Create test DataFrame
    import numpy as np
    test_df = pd.DataFrame({
        'timestamp': pd.date_range('2024-01-01', periods=100, freq='1H'),
        'open': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'close': np.random.randn(100).cumsum() + 100,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    # Test routing
    router = RegimeRouter(test_config)
    mock_context = MockContext("bull")
    
    print("Testing RegimeRouter...")
    print(f"Strategy health: {router.get_strategy_health()}")
    
    # This would normally execute, but requires actual strategy modules
    # result = router.route(test_df, mock_context, test_config)
    # print(f"Routing result: {result}")