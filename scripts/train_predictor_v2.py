"""
Train Enhanced ML Predictor V2 (scripts/train_predictor_v2.py)

Trains the enhanced predictor on historical data with:
- Sentiment features
- Whale flow detection
- Liquidations tracking
- Funding rate analysis

Usage:
    python scripts/train_predictor_v2.py --pairs BTC/USD,ETH/USD --days 180
    python scripts/train_predictor_v2.py --load-cached  # Use cached data

Author: Crypto AI Bot Team
Version: 2.0.0
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from ml.predictor_v2 import EnhancedPredictorV2
from ai_engine.whale_detection import detect_whale_flow
from ai_engine.liquidations_tracker import LiquidationsTracker

logger = logging.getLogger(__name__)


def load_historical_data(
    pair: str,
    days: int = 180,
    cache_dir: Path = Path("data/cache"),
) -> pd.DataFrame:
    """
    Load historical OHLCV data for training.

    Args:
        pair: Trading pair (e.g., "BTC/USD")
        days: Number of days to load
        cache_dir: Cache directory for historical data

    Returns:
        DataFrame with OHLCV data
    """
    cache_file = cache_dir / f"{pair.replace('/', '_')}_{days}d.parquet"

    # Try loading from cache
    if cache_file.exists():
        logger.info("Loading cached data from %s", cache_file)
        df = pd.read_parquet(cache_file)
        return df

    # Generate synthetic data for demonstration
    # In production, fetch from exchange API or database
    logger.warning("Cache not found, generating synthetic data")

    np.random.seed(42)
    n_bars = days * 24 * 12  # 5-min bars

    # Generate realistic price series (random walk with drift)
    start_price = 50000.0 if "BTC" in pair else 3000.0
    returns = np.random.normal(0.0001, 0.02, n_bars)  # Small positive drift
    prices = start_price * np.exp(np.cumsum(returns))

    # Generate OHLC from close
    noise = 0.002  # 0.2% noise
    df = pd.DataFrame({
        "timestamp": pd.date_range(end=pd.Timestamp.now(), periods=n_bars, freq="5T"),
        "open": prices * (1 + np.random.uniform(-noise, noise, n_bars)),
        "high": prices * (1 + np.random.uniform(0, noise * 2, n_bars)),
        "low": prices * (1 - np.random.uniform(0, noise * 2, n_bars)),
        "close": prices,
        "volume": np.random.exponential(100, n_bars),
    })

    # Calculate ATR
    df["atr"] = df["close"] * 0.02  # 2% ATR

    # Cache for future use
    cache_dir.mkdir(parents=True, exist_ok=True)
    df.to_parquet(cache_file)
    logger.info("Cached data to %s", cache_file)

    return df


def generate_training_labels(df: pd.DataFrame, lookahead_bars: int = 12) -> pd.Series:
    """
    Generate training labels (future returns).

    Label = 1 if price increases in next N bars, else 0

    Args:
        df: OHLCV DataFrame
        lookahead_bars: Bars to look ahead for label (default 12 = 1 hour for 5m bars)

    Returns:
        Series of binary labels (0/1)
    """
    future_returns = df["close"].shift(-lookahead_bars) / df["close"] - 1.0
    labels = (future_returns > 0).astype(int)

    # Drop NaN labels at the end
    labels = labels.fillna(0)

    return labels


def create_training_samples(
    df: pd.DataFrame,
    pair: str,
    sample_every: int = 10,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Create training samples (X, y) from historical data.

    Args:
        df: OHLCV DataFrame
        pair: Trading pair
        sample_every: Sample every N bars to reduce dataset size

    Returns:
        (X, y) where X is features [n_samples, 20] and y is labels [n_samples]
    """
    logger.info("Creating training samples for %s (n_bars=%d)", pair, len(df))

    # Generate labels
    y = generate_training_labels(df, lookahead_bars=12)

    # Initialize predictor for feature extraction
    predictor = EnhancedPredictorV2(use_lightgbm=False)  # Don't need model yet

    # Generate synthetic sentiment data
    # In production, load from database
    np.random.seed(42)
    sentiment_df = pd.DataFrame({
        "tw_score": np.random.normal(0.05, 0.2, len(df)),
        "tw_volume": np.random.exponential(100, len(df)),
        "rd_score": np.random.normal(0.03, 0.15, len(df)),
        "rd_volume": np.random.exponential(80, len(df)),
        "news_score": np.random.normal(0.02, 0.1, len(df)),
        "news_volume": np.random.exponential(50, len(df)),
        "news_dispersion": np.random.exponential(1.5, len(df)),
        "ret_5m": df["close"].pct_change(),
        "ret_1h": df["close"].pct_change(12),
        "mentions_btc": np.random.poisson(150, len(df)),
        "mentions_eth": np.random.poisson(100, len(df)),
    })

    # Extract features for each sample
    X_list = []
    y_list = []

    window_size = 100  # Need 100 bars for technical indicators

    for i in range(window_size, len(df) - 12, sample_every):  # Skip lookahead bars at end
        # Slice data up to current bar
        ohlcv_window = df.iloc[:i+1].copy()
        sentiment_window = sentiment_df.iloc[:i+1].copy()

        # Create context
        ctx = {
            "ohlcv_df": ohlcv_window,
            "current_price": float(df["close"].iloc[i]),
            "timeframe": "5m",
            "sentiment_df": sentiment_window,
            "funding_rate": np.random.normal(0.0001, 0.00005),  # Mock funding
        }

        try:
            # Extract features
            features = predictor._compute_enhanced_features(ctx)
            X_list.append(features)
            y_list.append(y.iloc[i])

        except Exception as e:
            logger.warning("Feature extraction failed at bar %d: %s", i, e)
            continue

    X = np.array(X_list)
    y_array = np.array(y_list)

    logger.info("Created %d training samples (20 features)", len(X))

    return X, y_array


def train_and_save_model(
    pairs: List[str],
    days: int = 180,
    test_split: float = 0.2,
    output_path: Path = Path("models/predictor_v2.pkl"),
) -> EnhancedPredictorV2:
    """
    Train enhanced predictor on multiple pairs and save to disk.

    Args:
        pairs: List of trading pairs
        days: Days of historical data
        test_split: Fraction of data for testing
        output_path: Path to save trained model

    Returns:
        Trained EnhancedPredictorV2
    """
    logger.info("Training enhanced predictor on %d pairs (%d days)", len(pairs), days)

    # Collect training data from all pairs
    X_all = []
    y_all = []

    for pair in pairs:
        logger.info("Loading data for %s...", pair)
        df = load_historical_data(pair, days=days)

        X, y = create_training_samples(df, pair, sample_every=10)
        X_all.append(X)
        y_all.append(y)

    # Concatenate all pairs
    X_train_full = np.vstack(X_all)
    y_train_full = np.concatenate(y_all)

    logger.info("Total samples: %d", len(X_train_full))

    # Train/test split
    n_train = int(len(X_train_full) * (1 - test_split))
    X_train = X_train_full[:n_train]
    y_train = y_train_full[:n_train]
    X_test = X_train_full[n_train:]
    y_test = y_train_full[n_train:]

    logger.info("Train samples: %d, Test samples: %d", len(X_train), len(X_test))

    # Create and train predictor
    try:
        import lightgbm as lgb
        use_lightgbm = True
        logger.info("Using LightGBM for training")
    except ImportError:
        use_lightgbm = False
        logger.warning("LightGBM not available, using sklearn fallback")

    predictor = EnhancedPredictorV2(use_lightgbm=use_lightgbm)

    # Train
    logger.info("Training model...")
    predictor.fit(X_train, y_train)

    # Evaluate on test set
    logger.info("Evaluating on test set...")
    test_preds = []
    for i in range(len(X_test)):
        # Create mock context with features already computed
        # For testing, we just need the features in the right format
        mock_ctx = {
            "ohlcv_df": pd.DataFrame({"close": [50000]}),
            "current_price": 50000.0,
            "timeframe": "5m",
        }
        # Hack: directly use test features
        predictor._compute_enhanced_features = lambda ctx: X_test[i]
        prob = predictor.predict_proba(mock_ctx)
        test_preds.append(1 if prob > 0.5 else 0)

    # Calculate metrics
    accuracy = np.mean(np.array(test_preds) == y_test)
    precision = np.sum((np.array(test_preds) == 1) & (y_test == 1)) / max(1, np.sum(np.array(test_preds) == 1))
    recall = np.sum((np.array(test_preds) == 1) & (y_test == 1)) / max(1, np.sum(y_test == 1))

    logger.info("Test Accuracy: %.2f%%", accuracy * 100)
    logger.info("Test Precision: %.2f%%", precision * 100)
    logger.info("Test Recall: %.2f%%", recall * 100)

    # Feature importance
    importance = predictor.get_feature_importance()
    logger.info("Top 10 features:")
    for feat, score in sorted(importance.items(), key=lambda x: -x[1])[:10]:
        logger.info("  %s: %.2f", feat, score)

    # Save model
    logger.info("Saving model to %s", output_path)
    predictor.save_model(output_path)

    return predictor


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Train Enhanced ML Predictor V2")
    parser.add_argument(
        "--pairs",
        type=str,
        default="BTC/USD,ETH/USD",
        help="Comma-separated list of trading pairs",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=180,
        help="Days of historical data to use",
    )
    parser.add_argument(
        "--test-split",
        type=float,
        default=0.2,
        help="Fraction of data for testing",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="models/predictor_v2.pkl",
        help="Output path for trained model",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse pairs
    pairs = [p.strip() for p in args.pairs.split(",")]

    # Train model
    try:
        predictor = train_and_save_model(
            pairs=pairs,
            days=args.days,
            test_split=args.test_split,
            output_path=Path(args.output),
        )

        logger.info("Training complete!")
        logger.info("Model saved to: %s", args.output)
        logger.info("Model uses %d features", len(predictor.feature_names_))

        return 0

    except Exception as e:
        logger.exception("Training failed: %s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
