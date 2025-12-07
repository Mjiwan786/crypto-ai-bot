"""
Deep Learning Ensemble for Crypto Trading Signal Prediction.

Regime-adaptive ensemble combining LSTM, Transformer, and CNN models with
dynamic weighting based on market conditions.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from enum import Enum
from pathlib import Path
import json
import logging

from ml.models.lstm_model import LSTMModel
from ml.models.transformer_model import TransformerModel
from ml.models.cnn_model import CNNModel

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MarketRegime(Enum):
    """Market regime classifications."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class RegimeDetector:
    """
    Detects current market regime based on price action and volatility.

    Uses multiple indicators:
    - ADX for trend strength
    - ATR for volatility
    - Price momentum for trend direction
    """

    def __init__(self,
                 adx_threshold: float = 25.0,
                 atr_threshold_high: float = 0.03,
                 momentum_window: int = 20):
        """
        Args:
            adx_threshold: ADX above this = trending (default 25)
            atr_threshold_high: ATR above this = volatile (default 3%)
            momentum_window: Lookback for momentum calculation (default 20)
        """
        self.adx_threshold = adx_threshold
        self.atr_threshold_high = atr_threshold_high
        self.momentum_window = momentum_window

    def detect_regime(self, features: pd.DataFrame) -> MarketRegime:
        """
        Detect current market regime from feature dataframe.

        Args:
            features: DataFrame with engineered features

        Returns:
            MarketRegime enum value
        """
        try:
            # Get latest values
            latest = features.iloc[-1]

            # Extract regime indicators
            adx = latest.get('adx_14', 0)
            atr = latest.get('atr_14', 0)
            close = latest.get('close', 0)

            # Calculate momentum
            if len(features) >= self.momentum_window:
                momentum = (close / features['close'].iloc[-self.momentum_window] - 1)
            else:
                momentum = 0

            # Normalize ATR by price
            atr_normalized = atr / close if close > 0 else 0

            # Regime detection logic
            is_trending = adx > self.adx_threshold
            is_volatile = atr_normalized > self.atr_threshold_high
            is_bullish = momentum > 0

            if is_volatile:
                return MarketRegime.VOLATILE
            elif is_trending and is_bullish:
                return MarketRegime.TRENDING_UP
            elif is_trending and not is_bullish:
                return MarketRegime.TRENDING_DOWN
            else:
                return MarketRegime.RANGING

        except Exception as e:
            logger.warning(f"Regime detection failed: {e}. Defaulting to UNKNOWN.")
            return MarketRegime.UNKNOWN

    def get_regime_features(self, features: pd.DataFrame) -> Dict[str, float]:
        """
        Extract regime-related features for logging/monitoring.

        Args:
            features: DataFrame with engineered features

        Returns:
            Dictionary of regime features
        """
        latest = features.iloc[-1]
        close = latest.get('close', 0)

        # Calculate momentum
        if len(features) >= self.momentum_window:
            momentum = (close / features['close'].iloc[-self.momentum_window] - 1)
        else:
            momentum = 0

        atr = latest.get('atr_14', 0)
        atr_normalized = atr / close if close > 0 else 0

        return {
            'adx': latest.get('adx_14', 0),
            'atr_normalized': atr_normalized,
            'momentum': momentum,
            'volatility_percentile': latest.get('volatility_percentile_30', 0)
        }


class EnsembleWeighter:
    """
    Manages ensemble weights with regime-adaptive adjustment and
    performance-based updates.
    """

    # Base weights per model
    BASE_WEIGHTS = {
        'lstm': 0.40,
        'transformer': 0.35,
        'cnn': 0.25
    }

    # Regime-specific weight adjustments
    REGIME_ADJUSTMENTS = {
        MarketRegime.TRENDING_UP: {
            'lstm': 0.05,      # LSTM better at trends
            'transformer': 0.00,
            'cnn': -0.05
        },
        MarketRegime.TRENDING_DOWN: {
            'lstm': 0.05,
            'transformer': 0.00,
            'cnn': -0.05
        },
        MarketRegime.RANGING: {
            'lstm': -0.05,
            'transformer': 0.00,  # Transformer good at mean reversion
            'cnn': 0.05           # CNN catches short patterns
        },
        MarketRegime.VOLATILE: {
            'lstm': -0.05,
            'transformer': 0.10,  # Transformer handles chaos better
            'cnn': -0.05
        },
        MarketRegime.UNKNOWN: {
            'lstm': 0.00,
            'transformer': 0.00,
            'cnn': 0.00
        }
    }

    def __init__(self, performance_tracking: bool = True):
        """
        Args:
            performance_tracking: Enable performance-based weight updates
        """
        self.performance_tracking = performance_tracking
        self.performance_history = {
            'lstm': [],
            'transformer': [],
            'cnn': []
        }

    def get_weights(self, regime: MarketRegime) -> Dict[str, float]:
        """
        Get ensemble weights for current regime.

        Args:
            regime: Current market regime

        Returns:
            Dictionary of normalized weights per model
        """
        # Start with base weights
        weights = self.BASE_WEIGHTS.copy()

        # Apply regime adjustments
        adjustments = self.REGIME_ADJUSTMENTS.get(regime, {})
        for model, adjustment in adjustments.items():
            weights[model] += adjustment

        # Normalize to sum to 1.0
        total = sum(weights.values())
        weights = {k: v / total for k, v in weights.items()}

        return weights

    def update_performance(self, model_name: str, accuracy: float):
        """
        Update performance history for a model.

        Args:
            model_name: Name of the model ('lstm', 'transformer', 'cnn')
            accuracy: Recent prediction accuracy (0-1)
        """
        if self.performance_tracking and model_name in self.performance_history:
            self.performance_history[model_name].append(accuracy)

            # Keep only last 100 predictions
            if len(self.performance_history[model_name]) > 100:
                self.performance_history[model_name] = \
                    self.performance_history[model_name][-100:]

    def get_performance_stats(self) -> Dict[str, Dict[str, float]]:
        """
        Get performance statistics for all models.

        Returns:
            Dictionary of performance stats per model
        """
        stats = {}
        for model_name, history in self.performance_history.items():
            if len(history) > 0:
                stats[model_name] = {
                    'mean_accuracy': np.mean(history),
                    'std_accuracy': np.std(history),
                    'recent_accuracy': np.mean(history[-10:]) if len(history) >= 10 else np.mean(history),
                    'n_predictions': len(history)
                }
            else:
                stats[model_name] = {
                    'mean_accuracy': 0.0,
                    'std_accuracy': 0.0,
                    'recent_accuracy': 0.0,
                    'n_predictions': 0
                }
        return stats


class MLEnsemble(nn.Module):
    """
    Deep Learning Ensemble combining LSTM, Transformer, and CNN models.

    Features:
    - Regime-adaptive weighting
    - Soft voting with probability aggregation
    - Confidence score computation
    - Model versioning and persistence
    """

    def __init__(self,
                 input_size: int = 128,
                 seq_len: int = 60,
                 num_classes: int = 3,
                 device: str = 'cuda' if torch.cuda.is_available() else 'cpu'):
        """
        Args:
            input_size: Number of input features (default 128)
            seq_len: Sequence length (default 60)
            num_classes: Number of output classes (default 3)
            device: Device to run models on
        """
        super(MLEnsemble, self).__init__()

        self.input_size = input_size
        self.seq_len = seq_len
        self.num_classes = num_classes
        self.device = device

        # Initialize models
        logger.info("Initializing LSTM model...")
        self.lstm_model = LSTMModel(
            input_size=input_size,
            hidden_size=256,
            num_layers=3,
            dropout=0.3,
            num_classes=num_classes
        ).to(device)

        logger.info("Initializing Transformer model...")
        self.transformer_model = TransformerModel(
            input_size=input_size,
            d_model=512,
            nhead=8,
            num_encoder_layers=6,
            dim_feedforward=2048,
            dropout=0.1,
            num_classes=num_classes
        ).to(device)

        logger.info("Initializing CNN model...")
        self.cnn_model = CNNModel(
            input_size=input_size,
            seq_len=seq_len,
            num_classes=num_classes
        ).to(device)

        # Initialize regime detector and weighter
        self.regime_detector = RegimeDetector()
        self.ensemble_weighter = EnsembleWeighter(performance_tracking=True)

        # Class labels
        self.class_labels = ['SHORT', 'NEUTRAL', 'LONG']

        logger.info(f"MLEnsemble initialized on device: {device}")

    def forward(self, x: torch.Tensor) -> Tuple[torch.Tensor, Dict[str, torch.Tensor]]:
        """
        Forward pass through all models.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            Tuple of (ensemble_logits, individual_logits_dict)
        """
        # Get predictions from each model
        lstm_logits, _ = self.lstm_model(x)
        transformer_logits = self.transformer_model(x)
        cnn_logits = self.cnn_model(x)

        # Equal weight ensemble for training
        # (regime-adaptive weights used only for inference)
        ensemble_logits = (lstm_logits + transformer_logits + cnn_logits) / 3.0

        individual_logits = {
            'lstm': lstm_logits,
            'transformer': transformer_logits,
            'cnn': cnn_logits
        }

        return ensemble_logits, individual_logits

    def predict(self,
                x: torch.Tensor,
                features_df: Optional[pd.DataFrame] = None,
                regime: Optional[MarketRegime] = None) -> Dict:
        """
        Make prediction with regime-adaptive weighting.

        Args:
            x: Input tensor (batch, seq_len, features)
            features_df: Feature dataframe for regime detection
            regime: Pre-detected regime (optional)

        Returns:
            Dictionary with prediction results
        """
        self.eval()

        with torch.no_grad():
            # Ensure input is on correct device
            x = x.to(self.device)

            # Get individual model probabilities
            lstm_logits, _ = self.lstm_model(x)
            lstm_probs = F.softmax(lstm_logits, dim=-1)

            transformer_logits = self.transformer_model(x)
            transformer_probs = F.softmax(transformer_logits, dim=-1)

            cnn_logits = self.cnn_model(x)
            cnn_probs = F.softmax(cnn_logits, dim=-1)

            # Detect regime if not provided
            if regime is None and features_df is not None:
                regime = self.regime_detector.detect_regime(features_df)
            elif regime is None:
                regime = MarketRegime.UNKNOWN

            # Get regime-adaptive weights
            weights = self.ensemble_weighter.get_weights(regime)

            # Weighted ensemble probability
            ensemble_probs = (
                weights['lstm'] * lstm_probs +
                weights['transformer'] * transformer_probs +
                weights['cnn'] * cnn_probs
            )

            # Get predictions
            ensemble_pred = ensemble_probs.argmax(dim=-1)
            ensemble_confidence = ensemble_probs.max(dim=-1)[0]

            # Calculate agreement between models
            lstm_pred = lstm_probs.argmax(dim=-1)
            transformer_pred = transformer_probs.argmax(dim=-1)
            cnn_pred = cnn_probs.argmax(dim=-1)

            # Agreement score (0-1)
            predictions = torch.stack([lstm_pred, transformer_pred, cnn_pred], dim=0)
            agreement = (predictions == ensemble_pred).float().mean(dim=0)

            # Build result dictionary
            result = {
                'signal': self.class_labels[ensemble_pred.item()],
                'probabilities': {
                    'SHORT': ensemble_probs[0, 0].item(),
                    'NEUTRAL': ensemble_probs[0, 1].item(),
                    'LONG': ensemble_probs[0, 2].item()
                },
                'confidence': ensemble_confidence.item(),
                'agreement': agreement.item(),
                'regime': regime.value,
                'weights': weights,
                'individual_predictions': {
                    'lstm': {
                        'signal': self.class_labels[lstm_pred.item()],
                        'probabilities': lstm_probs[0].cpu().numpy().tolist(),
                        'confidence': lstm_probs.max().item()
                    },
                    'transformer': {
                        'signal': self.class_labels[transformer_pred.item()],
                        'probabilities': transformer_probs[0].cpu().numpy().tolist(),
                        'confidence': transformer_probs.max().item()
                    },
                    'cnn': {
                        'signal': self.class_labels[cnn_pred.item()],
                        'probabilities': cnn_probs[0].cpu().numpy().tolist(),
                        'confidence': cnn_probs.max().item()
                    }
                }
            }

            # Add regime features if available
            if features_df is not None:
                result['regime_features'] = self.regime_detector.get_regime_features(features_df)

            return result

    def save_ensemble(self, save_dir: str, version: str = "v1.0"):
        """
        Save all models and metadata.

        Args:
            save_dir: Directory to save models
            version: Version string for this ensemble
        """
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        # Save individual models
        logger.info(f"Saving ensemble version {version} to {save_dir}")

        torch.save(
            self.lstm_model.state_dict(),
            save_path / f"lstm_model_{version}.pt"
        )
        torch.save(
            self.transformer_model.state_dict(),
            save_path / f"transformer_model_{version}.pt"
        )
        torch.save(
            self.cnn_model.state_dict(),
            save_path / f"cnn_model_{version}.pt"
        )

        # Save ensemble metadata
        metadata = {
            'version': version,
            'input_size': self.input_size,
            'seq_len': self.seq_len,
            'num_classes': self.num_classes,
            'class_labels': self.class_labels,
            'base_weights': self.ensemble_weighter.BASE_WEIGHTS,
            'regime_adjustments': {
                k.value: v for k, v in self.ensemble_weighter.REGIME_ADJUSTMENTS.items()
            },
            'performance_stats': self.ensemble_weighter.get_performance_stats()
        }

        with open(save_path / f"ensemble_metadata_{version}.json", 'w') as f:
            json.dump(metadata, f, indent=2)

        logger.info(f"Ensemble saved successfully: {save_path}")

    def load_ensemble(self, save_dir: str, version: str = "v1.0"):
        """
        Load all models and metadata.

        Args:
            save_dir: Directory containing saved models
            version: Version string to load
        """
        save_path = Path(save_dir)

        logger.info(f"Loading ensemble version {version} from {save_dir}")

        # Load individual models
        self.lstm_model.load_state_dict(
            torch.load(save_path / f"lstm_model_{version}.pt", map_location=self.device)
        )
        self.transformer_model.load_state_dict(
            torch.load(save_path / f"transformer_model_{version}.pt", map_location=self.device)
        )
        self.cnn_model.load_state_dict(
            torch.load(save_path / f"cnn_model_{version}.pt", map_location=self.device)
        )

        # Load metadata
        with open(save_path / f"ensemble_metadata_{version}.json", 'r') as f:
            metadata = json.load(f)

        logger.info(f"Ensemble loaded successfully: {metadata['version']}")
        logger.info(f"Performance stats: {metadata.get('performance_stats', {})}")

    def get_model_info(self) -> Dict:
        """
        Get information about the ensemble.

        Returns:
            Dictionary with model architecture info
        """
        lstm_params = sum(p.numel() for p in self.lstm_model.parameters())
        transformer_params = sum(p.numel() for p in self.transformer_model.parameters())
        cnn_params = sum(p.numel() for p in self.cnn_model.parameters())
        total_params = lstm_params + transformer_params + cnn_params

        return {
            'total_parameters': total_params,
            'model_parameters': {
                'lstm': lstm_params,
                'transformer': transformer_params,
                'cnn': cnn_params
            },
            'input_size': self.input_size,
            'seq_len': self.seq_len,
            'num_classes': self.num_classes,
            'class_labels': self.class_labels,
            'device': self.device
        }


if __name__ == "__main__":
    # Test ensemble
    print("Testing ML Ensemble...")

    # Create sample data
    batch_size = 1
    seq_len = 60
    features = 128

    x = torch.randn(batch_size, seq_len, features)

    # Initialize ensemble
    print("\nInitializing ensemble...")
    ensemble = MLEnsemble(
        input_size=features,
        seq_len=seq_len,
        num_classes=3
    )

    # Test forward pass
    print("\nTesting forward pass...")
    logits, individual_logits = ensemble(x)
    print(f"Ensemble logits shape: {logits.shape}")
    print(f"Individual models: {list(individual_logits.keys())}")

    # Test prediction
    print("\nTesting prediction...")
    result = ensemble.predict(x)

    print(f"\nPrediction Result:")
    print(f"  Signal: {result['signal']}")
    print(f"  Confidence: {result['confidence']:.3f}")
    print(f"  Agreement: {result['agreement']:.3f}")
    print(f"  Regime: {result['regime']}")
    print(f"  Probabilities:")
    for signal, prob in result['probabilities'].items():
        print(f"    {signal}: {prob:.3f}")

    print(f"\n  Individual Predictions:")
    for model_name, pred in result['individual_predictions'].items():
        print(f"    {model_name}: {pred['signal']} (conf: {pred['confidence']:.3f})")

    # Test regime detection
    print("\nTesting regime detection...")

    # Create mock feature dataframe
    mock_features = pd.DataFrame({
        'close': np.random.randn(100) * 100 + 50000,
        'adx_14': np.random.randn(100) * 10 + 30,
        'atr_14': np.random.randn(100) * 50 + 200,
        'volatility_percentile_30': np.random.rand(100)
    })

    regime_detector = RegimeDetector()
    regime = regime_detector.detect_regime(mock_features)
    regime_features = regime_detector.get_regime_features(mock_features)

    print(f"  Detected regime: {regime.value}")
    print(f"  Regime features:")
    for feature, value in regime_features.items():
        print(f"    {feature}: {value:.3f}")

    # Test regime-adaptive prediction
    print("\nTesting regime-adaptive prediction...")
    result_adaptive = ensemble.predict(x, features_df=mock_features)
    print(f"  Signal: {result_adaptive['signal']}")
    print(f"  Regime: {result_adaptive['regime']}")
    print(f"  Weights: {result_adaptive['weights']}")

    # Test model info
    print("\nModel Information:")
    info = ensemble.get_model_info()
    print(f"  Total parameters: {info['total_parameters']:,}")
    print(f"  Model parameters:")
    for model, params in info['model_parameters'].items():
        print(f"    {model}: {params:,}")

    # Test save/load
    print("\nTesting save/load...")
    save_dir = "models/ensemble_test"
    ensemble.save_ensemble(save_dir, version="v1.0_test")

    # Create new ensemble and load
    ensemble2 = MLEnsemble(input_size=features, seq_len=seq_len, num_classes=3)
    ensemble2.load_ensemble(save_dir, version="v1.0_test")

    # Verify loaded ensemble works
    result2 = ensemble2.predict(x)
    print(f"  Loaded ensemble prediction: {result2['signal']}")

    print("\n✓ ML Ensemble test passed!")
