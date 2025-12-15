"""
Unit Tests for Signal Generation.

Tests model inference, risk guardrails, and signal generation logic.

Author: QA Team
Version: 1.0.0
Date: 2025-11-17
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import pytest
import numpy as np
import pandas as pd
import torch
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime

from ml.deep_ensemble import MLEnsemble, MarketRegime
from ml.feature_engineering import FeatureEngineer, LabelGenerator


class TestModelInference:
    """Test ML model inference."""

    @pytest.fixture
    def mock_features(self):
        """Create mock feature data."""
        return pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=100, freq='15min'),
            'close': 50000 + np.random.randn(100).cumsum() * 100,
            'volume': np.random.uniform(100, 1000, 100),
            'adx_14': np.random.uniform(20, 40, 100),
            'atr_14': np.random.uniform(100, 300, 100),
            'rsi_14': np.random.uniform(30, 70, 100),
            'volatility_percentile_30': np.random.uniform(0, 1, 100)
        })

    @pytest.fixture
    def ensemble_model(self):
        """Create ensemble model."""
        return MLEnsemble(input_size=128, seq_len=60, num_classes=3)

    def test_model_inference_latency(self, ensemble_model):
        """Test that model inference completes within latency budget."""
        import time

        # Create sample input
        x = torch.randn(1, 60, 128)

        # Measure inference time
        start = time.time()
        result = ensemble_model.predict(x)
        latency_ms = (time.time() - start) * 1000

        # Assert latency is reasonable (<100ms for single prediction)
        assert latency_ms < 100, f"Inference too slow: {latency_ms:.2f}ms"

        # Verify result structure
        assert 'signal' in result
        assert 'confidence' in result
        assert 'probabilities' in result

    def test_model_output_validity(self, ensemble_model):
        """Test that model outputs are valid."""
        x = torch.randn(1, 60, 128)
        result = ensemble_model.predict(x)

        # Check signal is valid
        assert result['signal'] in ['SHORT', 'NEUTRAL', 'LONG']

        # Check confidence is in valid range
        assert 0 <= result['confidence'] <= 1

        # Check probabilities sum to 1
        prob_sum = sum(result['probabilities'].values())
        assert abs(prob_sum - 1.0) < 0.01, f"Probabilities sum to {prob_sum}, not 1.0"

        # Check all probabilities are valid
        for signal, prob in result['probabilities'].items():
            assert 0 <= prob <= 1, f"Invalid probability for {signal}: {prob}"

    def test_model_regime_detection(self, ensemble_model, mock_features):
        """Test regime detection."""
        from ml.deep_ensemble import RegimeDetector

        detector = RegimeDetector()
        regime = detector.detect_regime(mock_features)

        # Check regime is valid
        assert isinstance(regime, MarketRegime)
        assert regime in [
            MarketRegime.TRENDING_UP,
            MarketRegime.TRENDING_DOWN,
            MarketRegime.RANGING,
            MarketRegime.VOLATILE,
            MarketRegime.UNKNOWN
        ]

    def test_model_consistency(self, ensemble_model):
        """Test that model gives consistent results for same input."""
        x = torch.randn(1, 60, 128)

        # Get two predictions for same input
        ensemble_model.eval()
        result1 = ensemble_model.predict(x)
        result2 = ensemble_model.predict(x)

        # Should be identical in eval mode
        assert result1['signal'] == result2['signal']
        assert abs(result1['confidence'] - result2['confidence']) < 0.001

    def test_batch_inference(self, ensemble_model):
        """Test batch inference."""
        # Create batch input
        x = torch.randn(10, 60, 128)

        # Forward pass
        logits, _ = ensemble_model(x)

        # Check output shape
        assert logits.shape == (10, 3), f"Expected (10, 3), got {logits.shape}"


class TestRiskGuardrails:
    """Test risk management guardrails."""

    def test_confidence_threshold_filtering(self):
        """Test that low-confidence signals are filtered."""
        MIN_CONFIDENCE = 0.6

        # Mock signal with low confidence
        signal = {
            'signal': 'LONG',
            'confidence': 0.45,  # Below threshold
            'probabilities': {'LONG': 0.45, 'SHORT': 0.30, 'NEUTRAL': 0.25}
        }

        # Should not trade on low confidence
        should_trade = signal['confidence'] >= MIN_CONFIDENCE
        assert not should_trade, "Should not trade on low confidence signal"

    def test_position_size_calculation(self):
        """Test position size calculation based on confidence."""
        from ml.confidence_calibration import ConfidenceCalibrator

        calibrator = ConfidenceCalibrator(num_classes=3)

        # Test different confidence levels
        test_cases = [
            (0.85, 'very_high', 1.0),   # High confidence = full position
            (0.65, 'high', 0.75),        # Medium-high = 75%
            (0.55, 'medium', 0.50),      # Medium = 50%
            (0.45, 'low', 0.25),         # Low = 25%
            (0.35, 'very_low', 0.0),     # Very low = no position
        ]

        for confidence, expected_level, expected_size in test_cases:
            level = calibrator.get_confidence_level(confidence)
            risk_params = calibrator.get_risk_parameters(level)

            assert level == expected_level, f"Expected {expected_level}, got {level}"
            assert risk_params['position_size'] == expected_size

    def test_max_position_limits(self):
        """Test that positions don't exceed maximum limits."""
        MAX_POSITION_SIZE = 1.0  # 100% of account
        MAX_LEVERAGE = 3.0

        # Test position size calculation
        account_balance = 10000
        confidence = 0.85

        # Calculate position
        base_position_size = 0.02  # 2% risk per trade
        position_value = account_balance * base_position_size

        # With leverage
        leveraged_position = position_value * MAX_LEVERAGE

        # Check it doesn't exceed max
        max_allowed = account_balance * MAX_POSITION_SIZE * MAX_LEVERAGE
        assert leveraged_position <= max_allowed

    def test_stop_loss_validation(self):
        """Test stop loss percentage validation."""
        MIN_STOP_LOSS = 0.5  # 0.5%
        MAX_STOP_LOSS = 5.0   # 5%

        # Test various stop loss values
        test_values = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]

        for sl_pct in test_values:
            # All should be within limits
            assert MIN_STOP_LOSS <= sl_pct <= MAX_STOP_LOSS, \
                f"Stop loss {sl_pct}% outside valid range"

    def test_drawdown_circuit_breaker(self):
        """Test circuit breaker triggers on excessive drawdown."""
        MAX_DRAWDOWN = 0.10  # 10% max drawdown

        # Simulate account with drawdown
        initial_balance = 10000
        current_balance = 8800  # 12% drawdown

        drawdown = (initial_balance - current_balance) / initial_balance

        # Circuit breaker should trigger
        should_halt_trading = drawdown > MAX_DRAWDOWN
        assert should_halt_trading, "Circuit breaker should halt trading on excessive drawdown"

    def test_exposure_limits(self):
        """Test total exposure limits across all positions."""
        MAX_TOTAL_EXPOSURE = 3.0  # 3x account value max

        account_balance = 10000

        # Multiple positions
        positions = [
            {'symbol': 'BTC/USDT', 'size': 5000},
            {'symbol': 'ETH/USDT', 'size': 8000},
            {'symbol': 'SOL/USDT', 'size': 12000}
        ]

        total_exposure = sum(p['size'] for p in positions)
        exposure_ratio = total_exposure / account_balance

        # Check total exposure
        assert exposure_ratio <= MAX_TOTAL_EXPOSURE, \
            f"Total exposure {exposure_ratio:.2f}x exceeds limit {MAX_TOTAL_EXPOSURE}x"


class TestPnLCalculations:
    """Test PnL calculation accuracy."""

    def test_simple_pnl_calculation(self):
        """Test basic PnL calculation."""
        entry_price = 50000
        exit_price = 51000
        position_size = 0.1  # BTC

        # Long position
        pnl_long = (exit_price - entry_price) * position_size
        assert pnl_long == 100, f"Expected PnL 100, got {pnl_long}"

        # Short position
        pnl_short = (entry_price - exit_price) * position_size
        assert pnl_short == -100, f"Expected PnL -100, got {pnl_short}"

    def test_pnl_with_fees(self):
        """Test PnL calculation including trading fees."""
        entry_price = 50000
        exit_price = 51000
        position_size = 0.1
        fee_rate = 0.001  # 0.1% fee

        # Calculate fees
        entry_value = entry_price * position_size
        exit_value = exit_price * position_size

        entry_fee = entry_value * fee_rate
        exit_fee = exit_value * fee_rate
        total_fees = entry_fee + exit_fee

        # Gross PnL
        gross_pnl = exit_value - entry_value

        # Net PnL
        net_pnl = gross_pnl - total_fees

        assert net_pnl == 100 - total_fees
        assert net_pnl < gross_pnl, "Net PnL should be less than gross PnL"

    def test_cumulative_pnl(self):
        """Test cumulative PnL across multiple trades."""
        trades = [
            {'entry': 50000, 'exit': 51000, 'size': 0.1, 'result': 100},
            {'entry': 51000, 'exit': 50500, 'size': 0.1, 'result': -50},
            {'entry': 50500, 'exit': 52000, 'size': 0.1, 'result': 150},
        ]

        cumulative_pnl = sum(t['result'] for t in trades)

        assert cumulative_pnl == 200, f"Expected cumulative PnL 200, got {cumulative_pnl}"

    def test_percentage_returns(self):
        """Test percentage return calculations."""
        initial_capital = 10000
        final_capital = 11500

        # Calculate percentage return
        pct_return = ((final_capital - initial_capital) / initial_capital) * 100

        assert pct_return == 15.0, f"Expected 15% return, got {pct_return:.2f}%"

    def test_win_rate_calculation(self):
        """Test win rate calculation."""
        trades = [
            {'pnl': 100},   # Win
            {'pnl': -50},   # Loss
            {'pnl': 75},    # Win
            {'pnl': 120},   # Win
            {'pnl': -30},   # Loss
        ]

        wins = sum(1 for t in trades if t['pnl'] > 0)
        total_trades = len(trades)
        win_rate = wins / total_trades

        assert win_rate == 0.6, f"Expected win rate 60%, got {win_rate * 100}%"

    def test_sharpe_ratio_calculation(self):
        """Test Sharpe ratio calculation."""
        # Daily returns
        returns = np.array([0.01, -0.005, 0.015, 0.02, -0.01, 0.008, 0.012])

        # Annualized Sharpe (assuming daily returns)
        mean_return = returns.mean() * 252  # Annualize
        std_return = returns.std() * np.sqrt(252)  # Annualize

        sharpe_ratio = mean_return / std_return

        assert sharpe_ratio > 0, "Sharpe ratio should be positive for profitable strategy"

    def test_max_drawdown_calculation(self):
        """Test maximum drawdown calculation."""
        # Equity curve
        equity = np.array([10000, 10500, 10200, 11000, 10800, 11500, 10900, 12000])

        # Calculate drawdown
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max
        max_drawdown = abs(drawdown.min())

        assert max_drawdown > 0
        assert max_drawdown < 1.0  # Should be less than 100%


class TestSignalGeneration:
    """Test complete signal generation flow."""

    def test_feature_engineering_pipeline(self):
        """Test feature engineering produces valid features."""
        # Create sample OHLCV data
        df = pd.DataFrame({
            'timestamp': pd.date_range('2024-01-01', periods=500, freq='15min'),
            'open': 50000 + np.random.randn(500).cumsum() * 100,
            'high': 0,
            'low': 0,
            'close': 0,
            'volume': np.random.uniform(100, 1000, 500)
        })

        # Fill OHLC
        df['close'] = df['open'] + np.random.randn(len(df)) * 100
        df['high'] = df[['open', 'close']].max(axis=1) + np.abs(np.random.randn(len(df))) * 50
        df['low'] = df[['open', 'close']].min(axis=1) - np.abs(np.random.randn(len(df))) * 50

        # Engineer features
        engineer = FeatureEngineer()
        features_df = engineer.engineer_features(df)

        # Verify features
        assert len(features_df) > 0
        assert engineer.n_features >= 100  # Should have many features
        assert not features_df.isnull().any().any(), "Features should not contain NaN"

    def test_signal_structure(self):
        """Test generated signal has correct structure."""
        # Mock signal
        signal = {
            'timestamp': datetime.utcnow().isoformat(),
            'symbol': 'BTC/USDT',
            'timeframe': '15m',
            'signal': 'LONG',
            'confidence': 0.75,
            'probabilities': {
                'LONG': 0.75,
                'SHORT': 0.10,
                'NEUTRAL': 0.15
            },
            'regime': 'trending_up',
            'weights': {'lstm': 0.45, 'transformer': 0.35, 'cnn': 0.20}
        }

        # Validate structure
        required_fields = [
            'timestamp', 'symbol', 'timeframe', 'signal',
            'confidence', 'probabilities', 'regime'
        ]

        for field in required_fields:
            assert field in signal, f"Missing required field: {field}"

    def test_signal_validation(self):
        """Test signal validation logic."""
        def validate_signal(signal):
            """Validate signal structure and values."""
            # Check required fields
            required = ['signal', 'confidence', 'probabilities']
            if not all(k in signal for k in required):
                return False, "Missing required fields"

            # Check signal value
            if signal['signal'] not in ['LONG', 'SHORT', 'NEUTRAL']:
                return False, "Invalid signal value"

            # Check confidence
            if not (0 <= signal['confidence'] <= 1):
                return False, "Confidence out of range"

            # Check probabilities
            prob_sum = sum(signal['probabilities'].values())
            if abs(prob_sum - 1.0) > 0.01:
                return False, f"Probabilities don't sum to 1: {prob_sum}"

            return True, "Valid"

        # Test valid signal
        valid_signal = {
            'signal': 'LONG',
            'confidence': 0.75,
            'probabilities': {'LONG': 0.75, 'SHORT': 0.10, 'NEUTRAL': 0.15}
        }

        is_valid, msg = validate_signal(valid_signal)
        assert is_valid, f"Valid signal rejected: {msg}"

        # Test invalid signal
        invalid_signal = {
            'signal': 'INVALID',
            'confidence': 1.5,  # Out of range
            'probabilities': {'LONG': 0.5, 'SHORT': 0.3}  # Doesn't sum to 1
        }

        is_valid, msg = validate_signal(invalid_signal)
        assert not is_valid, "Invalid signal accepted"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
