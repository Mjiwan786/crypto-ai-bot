"""
Machine-learning agents for the crypto-ai-bot.

The modules in this package implement model training, prediction
and feature engineering. Sprint 4B replaced the stub implementations
with real wrappers around the trainer/ pipeline.
"""

from .feature_engineer import FeatureEngineer
from .predictor import StrategyPredictor

__all__ = ["FeatureEngineer", "StrategyPredictor"]
