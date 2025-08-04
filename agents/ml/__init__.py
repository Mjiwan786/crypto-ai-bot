"""
Machine‑learning agents for the crypto‑ai‑bot.

The modules in this package implement model training, prediction
and feature engineering.  They are intentionally kept lightweight
for this exercise; real implementations might integrate with
TensorFlow, PyTorch or other ML libraries.
"""

from .model_trainer import ModelTrainer
from .predictor import Predictor
from .feature_engineer import FeatureEngineer

__all__ = ["ModelTrainer", "Predictor", "FeatureEngineer"]