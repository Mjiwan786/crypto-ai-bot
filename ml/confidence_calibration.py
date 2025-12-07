"""
Confidence Calibration System for ML Predictions.

Implements Platt scaling and temperature scaling to calibrate model probabilities
and map them to confidence scores and risk parameters.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.optim as optim
import numpy as np
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from typing import Dict, Tuple, Optional
import logging
from pathlib import Path
import json

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TemperatureScaling(nn.Module):
    """
    Temperature scaling for calibrating neural network outputs.

    Learns a single temperature parameter T that scales logits before softmax:
    P(y|x) = softmax(z/T) where z are the logits.

    Reference: "On Calibration of Modern Neural Networks" (Guo et al., 2017)
    """

    def __init__(self):
        super(TemperatureScaling, self).__init__()
        # Initialize temperature to 1.0 (no scaling)
        self.temperature = nn.Parameter(torch.ones(1) * 1.0)

    def forward(self, logits: torch.Tensor) -> torch.Tensor:
        """
        Apply temperature scaling to logits.

        Args:
            logits: Raw logits from model (batch, num_classes)

        Returns:
            Temperature-scaled probabilities (batch, num_classes)
        """
        temperature = self.temperature.unsqueeze(1).expand(logits.size(0), logits.size(1))
        return torch.softmax(logits / temperature, dim=1)

    def fit(self,
            logits: torch.Tensor,
            labels: torch.Tensor,
            lr: float = 0.01,
            max_iter: int = 50) -> float:
        """
        Fit temperature parameter using validation set.

        Args:
            logits: Validation set logits (n_samples, num_classes)
            labels: True labels (n_samples,)
            lr: Learning rate (default 0.01)
            max_iter: Maximum iterations (default 50)

        Returns:
            Final NLL loss
        """
        nll_criterion = nn.CrossEntropyLoss()
        optimizer = optim.LBFGS([self.temperature], lr=lr, max_iter=max_iter)

        def eval():
            optimizer.zero_grad()
            loss = nll_criterion(self.forward(logits), labels)
            loss.backward()
            return loss

        optimizer.step(eval)

        # Calculate final loss
        with torch.no_grad():
            final_loss = nll_criterion(self.forward(logits), labels).item()

        logger.info(f"Temperature scaling fitted: T = {self.temperature.item():.4f}, NLL = {final_loss:.4f}")
        return final_loss


class PlattScaling:
    """
    Platt scaling for binary probability calibration.

    Fits a logistic regression model to map raw scores to calibrated probabilities.
    For multi-class, applies one-vs-rest approach.

    Reference: "Probabilistic Outputs for Support Vector Machines" (Platt, 1999)
    """

    def __init__(self, num_classes: int = 3):
        """
        Args:
            num_classes: Number of classes
        """
        self.num_classes = num_classes
        self.calibrators = {}  # One calibrator per class

    def _sigmoid(self, x: np.ndarray, A: float, B: float) -> np.ndarray:
        """
        Platt's sigmoid: P(y=1|f) = 1 / (1 + exp(A*f + B))

        Args:
            x: Scores
            A, B: Fitted parameters

        Returns:
            Calibrated probabilities
        """
        return 1.0 / (1.0 + np.exp(A * x + B))

    def fit(self, scores: np.ndarray, labels: np.ndarray) -> None:
        """
        Fit Platt scaling parameters for each class.

        Args:
            scores: Model scores (n_samples, num_classes)
            labels: True labels (n_samples,)
        """
        from scipy.optimize import minimize

        for class_idx in range(self.num_classes):
            # Binary labels: 1 if true class, 0 otherwise
            binary_labels = (labels == class_idx).astype(int)
            class_scores = scores[:, class_idx]

            # Objective: negative log-likelihood
            def objective(params):
                A, B = params
                probs = self._sigmoid(class_scores, A, B)
                # Clip to avoid log(0)
                probs = np.clip(probs, 1e-10, 1 - 1e-10)
                nll = -np.mean(
                    binary_labels * np.log(probs) +
                    (1 - binary_labels) * np.log(1 - probs)
                )
                return nll

            # Optimize
            result = minimize(objective, x0=[0.0, 0.0], method='BFGS')
            A, B = result.x

            self.calibrators[class_idx] = {'A': A, 'B': B}

            logger.info(f"Platt scaling for class {class_idx}: A={A:.4f}, B={B:.4f}")

    def predict_proba(self, scores: np.ndarray) -> np.ndarray:
        """
        Apply Platt scaling to get calibrated probabilities.

        Args:
            scores: Model scores (n_samples, num_classes)

        Returns:
            Calibrated probabilities (n_samples, num_classes)
        """
        calibrated_probs = np.zeros_like(scores)

        for class_idx in range(self.num_classes):
            params = self.calibrators.get(class_idx, {'A': 0.0, 'B': 0.0})
            calibrated_probs[:, class_idx] = self._sigmoid(
                scores[:, class_idx],
                params['A'],
                params['B']
            )

        # Normalize to sum to 1
        row_sums = calibrated_probs.sum(axis=1, keepdims=True)
        calibrated_probs = calibrated_probs / row_sums

        return calibrated_probs


class IsotonicCalibration:
    """
    Isotonic regression calibration (non-parametric).

    Fits a monotonic function to map predicted probabilities to calibrated probabilities.
    More flexible than Platt scaling but requires more data.
    """

    def __init__(self, num_classes: int = 3):
        """
        Args:
            num_classes: Number of classes
        """
        self.num_classes = num_classes
        self.calibrators = {}

    def fit(self, probs: np.ndarray, labels: np.ndarray) -> None:
        """
        Fit isotonic regression for each class.

        Args:
            probs: Predicted probabilities (n_samples, num_classes)
            labels: True labels (n_samples,)
        """
        for class_idx in range(self.num_classes):
            # Binary labels
            binary_labels = (labels == class_idx).astype(int)
            class_probs = probs[:, class_idx]

            # Fit isotonic regression
            iso_reg = IsotonicRegression(out_of_bounds='clip')
            iso_reg.fit(class_probs, binary_labels)

            self.calibrators[class_idx] = iso_reg

            logger.info(f"Isotonic calibration fitted for class {class_idx}")

    def predict_proba(self, probs: np.ndarray) -> np.ndarray:
        """
        Apply isotonic calibration.

        Args:
            probs: Predicted probabilities (n_samples, num_classes)

        Returns:
            Calibrated probabilities (n_samples, num_classes)
        """
        calibrated_probs = np.zeros_like(probs)

        for class_idx in range(self.num_classes):
            iso_reg = self.calibrators[class_idx]
            calibrated_probs[:, class_idx] = iso_reg.predict(probs[:, class_idx])

        # Normalize
        row_sums = calibrated_probs.sum(axis=1, keepdims=True)
        calibrated_probs = calibrated_probs / (row_sums + 1e-10)

        return calibrated_probs


class ConfidenceCalibrator:
    """
    Complete confidence calibration system.

    Combines multiple calibration methods and maps calibrated probabilities
    to confidence scores and risk parameters.
    """

    # Confidence score thresholds
    CONFIDENCE_THRESHOLDS = {
        'very_low': 0.40,
        'low': 0.50,
        'medium': 0.60,
        'high': 0.70,
        'very_high': 0.80
    }

    # Risk parameter mapping
    RISK_PARAMETERS = {
        'very_low': {
            'position_size': 0.0,  # No trade
            'stop_loss_pct': 0.0,
            'take_profit_pct': 0.0
        },
        'low': {
            'position_size': 0.25,  # 25% of normal
            'stop_loss_pct': 1.0,
            'take_profit_pct': 2.0
        },
        'medium': {
            'position_size': 0.50,  # 50% of normal
            'stop_loss_pct': 1.5,
            'take_profit_pct': 3.0
        },
        'high': {
            'position_size': 0.75,  # 75% of normal
            'stop_loss_pct': 2.0,
            'take_profit_pct': 4.0
        },
        'very_high': {
            'position_size': 1.0,  # 100% of normal
            'stop_loss_pct': 2.5,
            'take_profit_pct': 5.0
        }
    }

    def __init__(self,
                 num_classes: int = 3,
                 calibration_method: str = 'temperature',
                 device: str = 'cpu'):
        """
        Args:
            num_classes: Number of classes
            calibration_method: 'temperature', 'platt', or 'isotonic'
            device: Device for temperature scaling
        """
        self.num_classes = num_classes
        self.calibration_method = calibration_method
        self.device = device

        # Initialize calibrator
        if calibration_method == 'temperature':
            self.calibrator = TemperatureScaling().to(device)
        elif calibration_method == 'platt':
            self.calibrator = PlattScaling(num_classes=num_classes)
        elif calibration_method == 'isotonic':
            self.calibrator = IsotonicCalibration(num_classes=num_classes)
        else:
            raise ValueError(f"Unknown calibration method: {calibration_method}")

        self.is_fitted = False

    def fit(self,
            predictions: np.ndarray,
            labels: np.ndarray,
            logits: Optional[torch.Tensor] = None) -> None:
        """
        Fit calibration model on validation set.

        Args:
            predictions: Predicted probabilities (n_samples, num_classes)
            labels: True labels (n_samples,)
            logits: Raw logits for temperature scaling (optional)
        """
        logger.info(f"Fitting {self.calibration_method} calibration...")

        if self.calibration_method == 'temperature':
            if logits is None:
                raise ValueError("Temperature scaling requires logits")
            labels_tensor = torch.from_numpy(labels).long().to(self.device)
            self.calibrator.fit(logits, labels_tensor)

        elif self.calibration_method == 'platt':
            self.calibrator.fit(predictions, labels)

        elif self.calibration_method == 'isotonic':
            self.calibrator.fit(predictions, labels)

        self.is_fitted = True
        logger.info("Calibration fitted successfully")

    def calibrate(self,
                  predictions: Optional[np.ndarray] = None,
                  logits: Optional[torch.Tensor] = None) -> np.ndarray:
        """
        Apply calibration to predictions.

        Args:
            predictions: Predicted probabilities (n_samples, num_classes)
            logits: Raw logits for temperature scaling (optional)

        Returns:
            Calibrated probabilities (n_samples, num_classes)
        """
        if not self.is_fitted:
            logger.warning("Calibrator not fitted. Returning uncalibrated predictions.")
            return predictions

        if self.calibration_method == 'temperature':
            if logits is None:
                raise ValueError("Temperature scaling requires logits")
            with torch.no_grad():
                calibrated = self.calibrator(logits).cpu().numpy()

        elif self.calibration_method in ['platt', 'isotonic']:
            if predictions is None:
                raise ValueError(f"{self.calibration_method} requires predictions")
            calibrated = self.calibrator.predict_proba(predictions)

        return calibrated

    def get_confidence_level(self, max_prob: float) -> str:
        """
        Map probability to confidence level.

        Args:
            max_prob: Maximum class probability

        Returns:
            Confidence level string
        """
        if max_prob >= self.CONFIDENCE_THRESHOLDS['very_high']:
            return 'very_high'
        elif max_prob >= self.CONFIDENCE_THRESHOLDS['high']:
            return 'high'
        elif max_prob >= self.CONFIDENCE_THRESHOLDS['medium']:
            return 'medium'
        elif max_prob >= self.CONFIDENCE_THRESHOLDS['low']:
            return 'low'
        else:
            return 'very_low'

    def get_risk_parameters(self, confidence_level: str) -> Dict[str, float]:
        """
        Get risk parameters for confidence level.

        Args:
            confidence_level: Confidence level string

        Returns:
            Dictionary of risk parameters
        """
        return self.RISK_PARAMETERS.get(
            confidence_level,
            self.RISK_PARAMETERS['very_low']
        )

    def compute_calibration_metrics(self,
                                   predictions: np.ndarray,
                                   labels: np.ndarray,
                                   n_bins: int = 10) -> Dict[str, float]:
        """
        Compute calibration metrics.

        Args:
            predictions: Predicted probabilities (n_samples, num_classes)
            labels: True labels (n_samples,)
            n_bins: Number of bins for calibration curve

        Returns:
            Dictionary of calibration metrics
        """
        # Get predicted class and confidence
        pred_labels = predictions.argmax(axis=1)
        confidences = predictions.max(axis=1)
        correct = (pred_labels == labels).astype(float)

        # Compute Expected Calibration Error (ECE)
        ece = 0.0
        bin_edges = np.linspace(0, 1, n_bins + 1)

        for i in range(n_bins):
            bin_mask = (confidences >= bin_edges[i]) & (confidences < bin_edges[i + 1])
            if bin_mask.sum() > 0:
                bin_confidence = confidences[bin_mask].mean()
                bin_accuracy = correct[bin_mask].mean()
                bin_weight = bin_mask.sum() / len(confidences)
                ece += bin_weight * abs(bin_confidence - bin_accuracy)

        # Compute Maximum Calibration Error (MCE)
        mce = 0.0
        for i in range(n_bins):
            bin_mask = (confidences >= bin_edges[i]) & (confidences < bin_edges[i + 1])
            if bin_mask.sum() > 0:
                bin_confidence = confidences[bin_mask].mean()
                bin_accuracy = correct[bin_mask].mean()
                mce = max(mce, abs(bin_confidence - bin_accuracy))

        # Compute reliability diagram data
        prob_true, prob_pred = calibration_curve(
            correct, confidences, n_bins=n_bins, strategy='uniform'
        )

        return {
            'ece': ece,
            'mce': mce,
            'accuracy': correct.mean(),
            'avg_confidence': confidences.mean(),
            'calibration_curve': {
                'prob_true': prob_true.tolist(),
                'prob_pred': prob_pred.tolist()
            }
        }

    def save_calibrator(self, save_path: str) -> None:
        """
        Save calibration model.

        Args:
            save_path: Path to save calibrator
        """
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        if self.calibration_method == 'temperature':
            torch.save(self.calibrator.state_dict(), save_path)
        elif self.calibration_method in ['platt', 'isotonic']:
            import pickle
            with open(save_path, 'wb') as f:
                pickle.dump(self.calibrator, f)

        logger.info(f"Calibrator saved to {save_path}")

    def load_calibrator(self, save_path: str) -> None:
        """
        Load calibration model.

        Args:
            save_path: Path to load calibrator from
        """
        if self.calibration_method == 'temperature':
            self.calibrator.load_state_dict(torch.load(save_path, map_location=self.device))
        elif self.calibration_method in ['platt', 'isotonic']:
            import pickle
            with open(save_path, 'rb') as f:
                self.calibrator = pickle.load(f)

        self.is_fitted = True
        logger.info(f"Calibrator loaded from {save_path}")


if __name__ == "__main__":
    # Test calibration system
    print("Testing Confidence Calibration System...\n")

    # Create synthetic validation data
    np.random.seed(42)
    torch.manual_seed(42)

    n_samples = 1000
    num_classes = 3

    # Simulate uncalibrated predictions (overconfident)
    logits = torch.randn(n_samples, num_classes) * 2.0
    uncalibrated_probs = torch.softmax(logits, dim=1).numpy()
    true_labels = np.random.randint(0, num_classes, size=n_samples)

    print("1. Testing Temperature Scaling:")
    print("-" * 50)
    temp_calibrator = ConfidenceCalibrator(
        num_classes=num_classes,
        calibration_method='temperature'
    )
    temp_calibrator.fit(uncalibrated_probs, true_labels, logits=logits)
    calibrated_probs_temp = temp_calibrator.calibrate(logits=logits)

    print(f"Sample uncalibrated: {uncalibrated_probs[0]}")
    print(f"Sample calibrated:   {calibrated_probs_temp[0]}")

    metrics_before = temp_calibrator.compute_calibration_metrics(
        uncalibrated_probs, true_labels
    )
    metrics_after = temp_calibrator.compute_calibration_metrics(
        calibrated_probs_temp, true_labels
    )

    print(f"\nCalibration Metrics:")
    print(f"  Before: ECE = {metrics_before['ece']:.4f}, MCE = {metrics_before['mce']:.4f}")
    print(f"  After:  ECE = {metrics_after['ece']:.4f}, MCE = {metrics_after['mce']:.4f}")

    print("\n2. Testing Platt Scaling:")
    print("-" * 50)
    platt_calibrator = ConfidenceCalibrator(
        num_classes=num_classes,
        calibration_method='platt'
    )
    platt_calibrator.fit(uncalibrated_probs, true_labels)
    calibrated_probs_platt = platt_calibrator.calibrate(predictions=uncalibrated_probs)

    print(f"Sample uncalibrated: {uncalibrated_probs[0]}")
    print(f"Sample calibrated:   {calibrated_probs_platt[0]}")

    print("\n3. Testing Isotonic Calibration:")
    print("-" * 50)
    iso_calibrator = ConfidenceCalibrator(
        num_classes=num_classes,
        calibration_method='isotonic'
    )
    iso_calibrator.fit(uncalibrated_probs, true_labels)
    calibrated_probs_iso = iso_calibrator.calibrate(predictions=uncalibrated_probs)

    print(f"Sample uncalibrated: {uncalibrated_probs[0]}")
    print(f"Sample calibrated:   {calibrated_probs_iso[0]}")

    print("\n4. Testing Confidence Level Mapping:")
    print("-" * 50)
    test_confidences = [0.35, 0.45, 0.55, 0.65, 0.75, 0.85]
    for conf in test_confidences:
        level = temp_calibrator.get_confidence_level(conf)
        risk_params = temp_calibrator.get_risk_parameters(level)
        print(f"Confidence {conf:.2f} -> {level:12s} -> "
              f"Position: {risk_params['position_size']:.2f}, "
              f"SL: {risk_params['stop_loss_pct']:.1f}%, "
              f"TP: {risk_params['take_profit_pct']:.1f}%")

    print("\n5. Testing Save/Load:")
    print("-" * 50)
    save_path = "models/calibrator_test.pt"
    temp_calibrator.save_calibrator(save_path)

    # Load and test
    new_calibrator = ConfidenceCalibrator(
        num_classes=num_classes,
        calibration_method='temperature'
    )
    new_calibrator.load_calibrator(save_path)
    reloaded_probs = new_calibrator.calibrate(logits=logits)

    print(f"Original:  {calibrated_probs_temp[0]}")
    print(f"Reloaded:  {reloaded_probs[0]}")
    print(f"Match: {np.allclose(calibrated_probs_temp, reloaded_probs)}")

    print("\n✓ Confidence Calibration System test passed!")
