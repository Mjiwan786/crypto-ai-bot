import importlib
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel, ValidationError
from tenacity import retry, stop_after_attempt, wait_exponential
import pandas as pd
import numpy as np
from abc import ABC, abstractmethod

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StrategyConfig(BaseModel):
    """
    Pydantic model for strategy configuration validation
    """
    name: str
    module: str
    class_name: str
    enabled: bool = True
    params: dict = {}
    weight: float = 1.0  # For portfolio strategies
    risk_limit: Optional[float] = None

class StrategyExecutor:
    def __init__(self, exchange_client, data_provider, risk_manager):
        """
        Initialize the StrategyExecutor with required services.
        
        Args:
            exchange_client: Authenticated exchange client (ccxt or similar)
            data_provider: Data provider for market data
            risk_manager: Risk management service
        """
        self.exchange_client = exchange_client
        self.data_provider = data_provider
        self.risk_manager = risk_manager
        self.strategies: Dict[str, object] = {}
        self.active_strategies: Dict[str, StrategyConfig] = {}
        
        # Metrics tracking
        self.execution_count = 0
        self.success_count = 0
        self.error_count = 0

    def load_strategies(self, strategy_configs: List[dict]) -> bool:
        """
        Load and validate strategies from configuration.
        
        Args:
            strategy_configs: List of strategy configurations
            
        Returns:
            bool: True if all strategies loaded successfully
        """
        success = True
        for config in strategy_configs:
            try:
                validated_config = StrategyConfig(**config)
                if validated_config.enabled:
                    self._load_strategy(validated_config)
            except ValidationError as e:
                logger.error(f"Invalid strategy configuration {config}: {e}")
                success = False
            except Exception as e:
                logger.error(f"Failed to load strategy {config.get('name')}: {e}")
                success = False
        return success

    def _load_strategy(self, config: StrategyConfig) -> None:
        """
        Internal method to load a single strategy.
        
        Args:
            config: Validated strategy configuration
        """
        try:
            module = importlib.import_module(config.module)
            strategy_class = getattr(module, config.class_name)
            strategy_instance = strategy_class(
                exchange_client=self.exchange_client,
                data_provider=self.data_provider,
                **config.params
            )
            
            if not isinstance(strategy_instance, BaseTradingStrategy):
                raise TypeError(f"Strategy must inherit from BaseTradingStrategy")
                
            self.strategies[config.name] = strategy_instance
            self.active_strategies[config.name] = config
            logger.info(f"Successfully loaded strategy: {config.name}")
            
        except Exception as e:
            logger.error(f"Error loading strategy {config.name}: {str(e)}")
            raise

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    async def execute_strategy(self, strategy_name: str, symbol: str, timeframe: str = '1h') -> Optional[dict]:
        """
        Execute a single strategy for a given symbol and timeframe.
        
        Args:
            strategy_name: Name of the strategy to execute
            symbol: Trading symbol (e.g., 'BTC/USDT')
            timeframe: Timeframe for analysis (e.g., '1h', '4h', '1d')
            
        Returns:
            dict: Trade signal or None if no action
        """
        if strategy_name not in self.strategies:
            logger.error(f"Strategy {strategy_name} not found")
            return None
            
        strategy = self.strategies[strategy_name]
        config = self.active_strategies[strategy_name]
        
        try:
            # Get required data
            data = await self.data_provider.get_ohlcv(symbol, timeframe)
            
            # Check risk limits before execution
            if not self.risk_manager.check_strategy_risk(strategy_name, symbol):
                logger.warning(f"Risk limit exceeded for {strategy_name} on {symbol}")
                return None
                
            # Generate signal
            signal = await strategy.generate_signal(data, symbol, timeframe)
            
            if signal:
                # Validate signal with risk manager
                validated_signal = self.risk_manager.validate_signal(signal)
                if validated_signal:
                    self.success_count += 1
                    return validated_signal
                    
            self.execution_count += 1
            return None
            
        except Exception as e:
            self.error_count += 1
            logger.error(f"Error executing {strategy_name} on {symbol}: {str(e)}")
            raise

    async def execute_all_strategies(self, symbol: str, timeframe: str = '1h') -> Dict[str, dict]:
        """
        Execute all loaded strategies for a given symbol and timeframe.
        
        Args:
            symbol: Trading symbol
            timeframe: Timeframe for analysis
            
        Returns:
            Dict[str, dict]: Dictionary of strategy names to their signals
        """
        results = {}
        for strategy_name in self.active_strategies:
            try:
                signal = await self.execute_strategy(strategy_name, symbol, timeframe)
                if signal:
                    results[strategy_name] = signal
            except Exception as e:
                logger.error(f"Skipping {strategy_name} due to error: {str(e)}")
                continue
                
        return results

    def get_strategy_metrics(self) -> dict:
        """
        Get execution metrics for all strategies.
        
        Returns:
            dict: Strategy performance metrics
        """
        return {
            'total_executions': self.execution_count,
            'successful_executions': self.success_count,
            'error_count': self.error_count,
            'success_rate': self.success_count / self.execution_count if self.execution_count > 0 else 0
        }

class BaseTradingStrategy(ABC):
    """
    Abstract base class for all trading strategies
    """
    def __init__(self, exchange_client, data_provider, **params):
        self.exchange_client = exchange_client
        self.data_provider = data_provider
        self.params = params
        self.initialized = False
        
    @abstractmethod
    async def initialize(self):
        """Initialize the strategy"""
        pass
        
    @abstractmethod
    async def generate_signal(self, data: pd.DataFrame, symbol: str, timeframe: str) -> Optional[dict]:
        """
        Generate trading signal based on market data.
        
        Args:
            data: OHLCV market data
            symbol: Trading symbol
            timeframe: Timeframe of the data
            
        Returns:
            dict: Trading signal or None if no action
        """
        pass
        
    def calculate_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        Calculate technical indicators for the strategy.
        
        Args:
            data: OHLCV market data
            
        Returns:
            pd.DataFrame: Data with additional indicator columns
        """
        return data