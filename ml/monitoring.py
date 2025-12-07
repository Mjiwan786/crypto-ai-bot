"""
ML Model Monitoring and Drift Detection.

Tracks model performance, detects concept drift, and alerts when retraining
is needed.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from collections import deque
import json
import logging
from pathlib import Path
from scipy import stats

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class PerformanceTracker:
    """
    Track model performance metrics over time.

    Monitors accuracy, confidence, and trading metrics with rolling windows.
    """

    def __init__(self,
                 window_size: int = 1000,
                 alert_threshold: float = 0.05):
        """
        Args:
            window_size: Size of rolling window for metrics
            alert_threshold: Performance drop threshold for alerts
        """
        self.window_size = window_size
        self.alert_threshold = alert_threshold

        # Rolling windows for metrics
        self.predictions = deque(maxlen=window_size)
        self.true_labels = deque(maxlen=window_size)
        self.confidences = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)

        # Baseline metrics (from training/validation)
        self.baseline_accuracy = None
        self.baseline_confidence = None

    def set_baseline(self, accuracy: float, confidence: float) -> None:
        """
        Set baseline metrics from validation set.

        Args:
            accuracy: Baseline accuracy
            confidence: Baseline average confidence
        """
        self.baseline_accuracy = accuracy
        self.baseline_confidence = confidence
        logger.info(f"Baseline set: accuracy={accuracy:.4f}, confidence={confidence:.4f}")

    def update(self,
               prediction: int,
               true_label: int,
               confidence: float,
               timestamp: Optional[datetime] = None) -> None:
        """
        Update tracker with new prediction.

        Args:
            prediction: Predicted class
            true_label: True class
            confidence: Prediction confidence
            timestamp: Prediction timestamp
        """
        self.predictions.append(prediction)
        self.true_labels.append(true_label)
        self.confidences.append(confidence)
        self.timestamps.append(timestamp or datetime.utcnow())

    def get_current_metrics(self) -> Dict[str, float]:
        """
        Calculate current performance metrics.

        Returns:
            Dictionary of current metrics
        """
        if len(self.predictions) == 0:
            return {}

        predictions = np.array(self.predictions)
        true_labels = np.array(self.true_labels)
        confidences = np.array(self.confidences)

        # Calculate metrics
        accuracy = (predictions == true_labels).mean()
        avg_confidence = confidences.mean()
        std_confidence = confidences.std()

        # Per-class accuracy
        unique_labels = np.unique(true_labels)
        per_class_accuracy = {}
        for label in unique_labels:
            mask = true_labels == label
            if mask.sum() > 0:
                per_class_accuracy[int(label)] = (predictions[mask] == true_labels[mask]).mean()

        return {
            'accuracy': accuracy,
            'avg_confidence': avg_confidence,
            'std_confidence': std_confidence,
            'per_class_accuracy': per_class_accuracy,
            'sample_count': len(self.predictions)
        }

    def check_performance_degradation(self) -> Tuple[bool, Dict[str, float]]:
        """
        Check if performance has degraded significantly.

        Returns:
            Tuple of (is_degraded, degradation_metrics)
        """
        if self.baseline_accuracy is None or len(self.predictions) < 100:
            return False, {}

        current = self.get_current_metrics()
        current_accuracy = current['accuracy']
        current_confidence = current['avg_confidence']

        # Calculate degradation
        accuracy_drop = self.baseline_accuracy - current_accuracy
        confidence_drop = self.baseline_confidence - current_confidence

        degradation = {
            'accuracy_drop': accuracy_drop,
            'confidence_drop': confidence_drop,
            'current_accuracy': current_accuracy,
            'baseline_accuracy': self.baseline_accuracy
        }

        # Check if degraded
        is_degraded = (
            accuracy_drop > self.alert_threshold or
            confidence_drop > self.alert_threshold
        )

        if is_degraded:
            logger.warning(
                f"Performance degradation detected! "
                f"Accuracy drop: {accuracy_drop:.4f}, "
                f"Confidence drop: {confidence_drop:.4f}"
            )

        return is_degraded, degradation


class DriftDetector:
    """
    Detect concept drift in input features.

    Uses statistical tests to detect distribution shifts that may indicate
    the model needs retraining.
    """

    def __init__(self,
                 window_size: int = 1000,
                 reference_size: int = 1000,
                 drift_threshold: float = 0.05):
        """
        Args:
            window_size: Size of current window
            reference_size: Size of reference window
            drift_threshold: P-value threshold for drift detection
        """
        self.window_size = window_size
        self.reference_size = reference_size
        self.drift_threshold = drift_threshold

        # Reference distribution (from training)
        self.reference_data = None

        # Current window
        self.current_window = deque(maxlen=window_size)

    def set_reference(self, reference_data: np.ndarray) -> None:
        """
        Set reference distribution from training data.

        Args:
            reference_data: Reference feature data (n_samples, n_features)
        """
        # Sample if too large
        if len(reference_data) > self.reference_size:
            indices = np.random.choice(
                len(reference_data),
                size=self.reference_size,
                replace=False
            )
            self.reference_data = reference_data[indices]
        else:
            self.reference_data = reference_data

        logger.info(f"Reference distribution set: {self.reference_data.shape}")

    def update(self, features: np.ndarray) -> None:
        """
        Update current window with new features.

        Args:
            features: Feature vector (n_features,)
        """
        self.current_window.append(features)

    def detect_drift(self) -> Tuple[bool, Dict[str, float]]:
        """
        Detect drift using Kolmogorov-Smirnov test.

        Returns:
            Tuple of (is_drift, drift_metrics)
        """
        if self.reference_data is None or len(self.current_window) < 100:
            return False, {}

        current_data = np.array(self.current_window)
        n_features = current_data.shape[1]

        # Test each feature for drift
        drift_pvalues = []
        drift_statistics = []

        for i in range(n_features):
            ref_feature = self.reference_data[:, i]
            curr_feature = current_data[:, i]

            # Kolmogorov-Smirnov test
            statistic, pvalue = stats.ks_2samp(ref_feature, curr_feature)

            drift_pvalues.append(pvalue)
            drift_statistics.append(statistic)

        # Calculate drift metrics
        avg_pvalue = np.mean(drift_pvalues)
        min_pvalue = np.min(drift_pvalues)
        drift_ratio = (np.array(drift_pvalues) < self.drift_threshold).mean()

        drift_metrics = {
            'avg_pvalue': avg_pvalue,
            'min_pvalue': min_pvalue,
            'drift_ratio': drift_ratio,  # Fraction of features showing drift
            'drifted_features': int(drift_ratio * n_features)
        }

        # Detect drift if significant portion of features drifted
        is_drift = drift_ratio > 0.1  # More than 10% of features

        if is_drift:
            logger.warning(
                f"Concept drift detected! "
                f"{drift_ratio * 100:.1f}% of features drifted "
                f"(p-value < {self.drift_threshold})"
            )

        return is_drift, drift_metrics

    def detect_drift_psi(self, n_bins: int = 10) -> Tuple[bool, float]:
        """
        Detect drift using Population Stability Index (PSI).

        PSI is commonly used in credit scoring for monitoring.

        Args:
            n_bins: Number of bins for discretization

        Returns:
            Tuple of (is_drift, psi_score)
        """
        if self.reference_data is None or len(self.current_window) < 100:
            return False, 0.0

        current_data = np.array(self.current_window)
        n_features = current_data.shape[1]

        psi_scores = []

        for i in range(n_features):
            ref_feature = self.reference_data[:, i]
            curr_feature = current_data[:, i]

            # Create bins based on reference distribution
            _, bin_edges = np.histogram(ref_feature, bins=n_bins)

            # Calculate distributions
            ref_dist, _ = np.histogram(ref_feature, bins=bin_edges, density=True)
            curr_dist, _ = np.histogram(curr_feature, bins=bin_edges, density=True)

            # Normalize to probabilities
            ref_dist = ref_dist / ref_dist.sum()
            curr_dist = curr_dist / curr_dist.sum()

            # Add small epsilon to avoid log(0)
            ref_dist = np.maximum(ref_dist, 1e-10)
            curr_dist = np.maximum(curr_dist, 1e-10)

            # Calculate PSI
            psi = np.sum((curr_dist - ref_dist) * np.log(curr_dist / ref_dist))
            psi_scores.append(psi)

        # Average PSI across features
        avg_psi = np.mean(psi_scores)

        # PSI interpretation:
        # < 0.1: No significant drift
        # 0.1-0.25: Moderate drift
        # > 0.25: Significant drift
        is_drift = avg_psi > 0.1

        if is_drift:
            logger.warning(f"Drift detected (PSI): {avg_psi:.4f}")

        return is_drift, avg_psi


class ModelMonitor:
    """
    Complete model monitoring system.

    Combines performance tracking and drift detection with alerting.
    """

    def __init__(self,
                 model_name: str = "ensemble",
                 performance_window: int = 1000,
                 drift_window: int = 1000,
                 alert_callback: Optional[callable] = None):
        """
        Args:
            model_name: Name of model being monitored
            performance_window: Window size for performance tracking
            drift_window: Window size for drift detection
            alert_callback: Function to call when alerts triggered
        """
        self.model_name = model_name
        self.alert_callback = alert_callback

        # Initialize trackers
        self.performance_tracker = PerformanceTracker(
            window_size=performance_window
        )
        self.drift_detector = DriftDetector(
            window_size=drift_window
        )

        # Monitoring state
        self.monitoring_active = False
        self.alerts = []

    def initialize(self,
                  baseline_accuracy: float,
                  baseline_confidence: float,
                  reference_features: np.ndarray) -> None:
        """
        Initialize monitoring with baseline metrics and reference data.

        Args:
            baseline_accuracy: Baseline accuracy from validation
            baseline_confidence: Baseline confidence from validation
            reference_features: Reference feature distribution
        """
        self.performance_tracker.set_baseline(baseline_accuracy, baseline_confidence)
        self.drift_detector.set_reference(reference_features)
        self.monitoring_active = True
        logger.info(f"Monitoring initialized for {self.model_name}")

    def update(self,
               prediction: int,
               true_label: int,
               confidence: float,
               features: np.ndarray,
               timestamp: Optional[datetime] = None) -> None:
        """
        Update monitoring with new prediction.

        Args:
            prediction: Predicted class
            true_label: True class
            confidence: Prediction confidence
            features: Input features
            timestamp: Prediction timestamp
        """
        if not self.monitoring_active:
            logger.warning("Monitoring not initialized!")
            return

        # Update trackers
        self.performance_tracker.update(prediction, true_label, confidence, timestamp)
        self.drift_detector.update(features)

        # Check for issues periodically
        if len(self.performance_tracker.predictions) % 100 == 0:
            self.check_health()

    def check_health(self) -> Dict[str, any]:
        """
        Check model health and generate alerts if needed.

        Returns:
            Health status dictionary
        """
        health_status = {
            'timestamp': datetime.utcnow().isoformat(),
            'model_name': self.model_name,
            'healthy': True,
            'alerts': []
        }

        # Check performance degradation
        is_degraded, degradation = self.performance_tracker.check_performance_degradation()
        if is_degraded:
            alert = {
                'type': 'performance_degradation',
                'severity': 'high',
                'details': degradation
            }
            health_status['alerts'].append(alert)
            health_status['healthy'] = False
            self._trigger_alert(alert)

        # Check drift
        is_drift, drift_metrics = self.drift_detector.detect_drift()
        if is_drift:
            alert = {
                'type': 'concept_drift',
                'severity': 'medium',
                'details': drift_metrics
            }
            health_status['alerts'].append(alert)
            health_status['healthy'] = False
            self._trigger_alert(alert)

        # Add current metrics
        health_status['current_metrics'] = self.performance_tracker.get_current_metrics()

        return health_status

    def _trigger_alert(self, alert: Dict) -> None:
        """
        Trigger alert callback.

        Args:
            alert: Alert dictionary
        """
        self.alerts.append({
            'timestamp': datetime.utcnow().isoformat(),
            **alert
        })

        logger.warning(f"ALERT: {alert['type']} - {alert['severity']}")

        if self.alert_callback is not None:
            self.alert_callback(alert)

    def get_monitoring_report(self) -> Dict:
        """
        Generate comprehensive monitoring report.

        Returns:
            Monitoring report dictionary
        """
        current_metrics = self.performance_tracker.get_current_metrics()
        health = self.check_health()

        report = {
            'model_name': self.model_name,
            'timestamp': datetime.utcnow().isoformat(),
            'monitoring_active': self.monitoring_active,
            'current_metrics': current_metrics,
            'baseline_metrics': {
                'accuracy': self.performance_tracker.baseline_accuracy,
                'confidence': self.performance_tracker.baseline_confidence
            },
            'health_status': health,
            'recent_alerts': self.alerts[-10:] if len(self.alerts) > 0 else []
        }

        return report

    def save_report(self, save_path: str) -> None:
        """
        Save monitoring report to file.

        Args:
            save_path: Path to save report
        """
        report = self.get_monitoring_report()

        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)

        with open(save_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Monitoring report saved to {save_path}")


if __name__ == "__main__":
    # Test monitoring system
    print("Testing Model Monitoring System...\n")

    # Create synthetic data
    np.random.seed(42)

    n_samples = 2000
    n_features = 128

    # Reference data (training distribution)
    reference_features = np.random.randn(n_samples, n_features)

    # Baseline metrics
    baseline_accuracy = 0.75
    baseline_confidence = 0.72

    # Initialize monitor
    print("1. Initializing Monitor:")
    monitor = ModelMonitor(
        model_name="test_ensemble",
        performance_window=1000,
        drift_window=1000
    )

    monitor.initialize(
        baseline_accuracy=baseline_accuracy,
        baseline_confidence=baseline_confidence,
        reference_features=reference_features
    )

    # Simulate predictions with good performance
    print("\n2. Simulating Good Performance:")
    for i in range(500):
        # Generate features from same distribution
        features = np.random.randn(n_features)

        # Simulate predictions (75% accuracy)
        true_label = np.random.randint(0, 3)
        prediction = true_label if np.random.rand() < 0.75 else np.random.randint(0, 3)
        confidence = np.random.uniform(0.6, 0.9)

        monitor.update(prediction, true_label, confidence, features)

    metrics = monitor.performance_tracker.get_current_metrics()
    print(f"   Current accuracy: {metrics['accuracy']:.4f}")
    print(f"   Current confidence: {metrics['avg_confidence']:.4f}")

    # Simulate performance degradation
    print("\n3. Simulating Performance Degradation:")
    for i in range(500):
        features = np.random.randn(n_features)

        # Lower accuracy (50%)
        true_label = np.random.randint(0, 3)
        prediction = true_label if np.random.rand() < 0.50 else np.random.randint(0, 3)
        confidence = np.random.uniform(0.4, 0.7)

        monitor.update(prediction, true_label, confidence, features)

    health = monitor.check_health()
    print(f"   Healthy: {health['healthy']}")
    print(f"   Alerts: {len(health['alerts'])}")
    for alert in health['alerts']:
        print(f"     - {alert['type']}: {alert['severity']}")

    # Simulate concept drift
    print("\n4. Simulating Concept Drift:")
    for i in range(500):
        # Features from different distribution (shifted)
        features = np.random.randn(n_features) + 2.0  # Shift distribution

        true_label = np.random.randint(0, 3)
        prediction = true_label if np.random.rand() < 0.70 else np.random.randint(0, 3)
        confidence = np.random.uniform(0.6, 0.8)

        monitor.update(prediction, true_label, confidence, features)

    health = monitor.check_health()
    print(f"   Healthy: {health['healthy']}")
    print(f"   Alerts: {len(health['alerts'])}")
    for alert in health['alerts']:
        print(f"     - {alert['type']}: {alert['severity']}")

    # Generate report
    print("\n5. Generating Monitoring Report:")
    report = monitor.get_monitoring_report()
    print(f"   Model: {report['model_name']}")
    print(f"   Monitoring Active: {report['monitoring_active']}")
    print(f"   Current Accuracy: {report['current_metrics']['accuracy']:.4f}")
    print(f"   Baseline Accuracy: {report['baseline_metrics']['accuracy']:.4f}")
    print(f"   Total Alerts: {len(report['recent_alerts'])}")

    # Save report
    monitor.save_report("models/test_monitoring_report.json")

    print("\n✓ Model Monitoring System test passed!")
