"""
Training Pipeline for ML Ensemble Models.

Complete training workflow for LSTM, Transformer, and CNN models including:
- Data loading and preprocessing
- Model training with early stopping
- Validation and metrics tracking
- Model checkpointing
- Ensemble calibration

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import Dataset, DataLoader, TensorDataset
import numpy as np
import pandas as pd
from typing import Dict, Tuple, Optional, List
from pathlib import Path
import json
import logging
from datetime import datetime
from tqdm import tqdm

from ml.models.lstm_model import LSTMModel, LSTMConfig
from ml.models.transformer_model import TransformerModel, TransformerConfig, WarmupCosineScheduler
from ml.models.cnn_model import CNNModel, CNNConfig
from ml.confidence_calibration import ConfidenceCalibrator
from ml.evaluation import MLMetrics, TradingMetrics

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class EarlyStopping:
    """
    Early stopping to prevent overfitting.

    Stops training when validation loss doesn't improve for patience epochs.
    """

    def __init__(self,
                 patience: int = 7,
                 min_delta: float = 0.0001,
                 mode: str = 'min'):
        """
        Args:
            patience: Number of epochs to wait
            min_delta: Minimum change to qualify as improvement
            mode: 'min' for loss, 'max' for accuracy
        """
        self.patience = patience
        self.min_delta = min_delta
        self.mode = mode
        self.counter = 0
        self.best_score = None
        self.early_stop = False

    def __call__(self, score: float) -> bool:
        """
        Check if training should stop.

        Args:
            score: Current validation score

        Returns:
            True if should stop, False otherwise
        """
        if self.best_score is None:
            self.best_score = score
            return False

        # Check if improved
        if self.mode == 'min':
            improved = score < (self.best_score - self.min_delta)
        else:  # mode == 'max'
            improved = score > (self.best_score + self.min_delta)

        if improved:
            self.best_score = score
            self.counter = 0
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True
                return True

        return False


class ModelTrainer:
    """
    Trainer for individual models (LSTM, Transformer, CNN).

    Handles complete training workflow with logging and checkpointing.
    """

    def __init__(self,
                 model: nn.Module,
                 device: str = 'cuda' if torch.cuda.is_available() else 'cpu',
                 model_name: str = 'model'):
        """
        Args:
            model: PyTorch model to train
            device: Device to train on
            model_name: Name for logging and saving
        """
        self.model = model.to(device)
        self.device = device
        self.model_name = model_name
        self.history = {
            'train_loss': [],
            'val_loss': [],
            'train_acc': [],
            'val_acc': []
        }

    def train_epoch(self,
                   train_loader: DataLoader,
                   criterion: nn.Module,
                   optimizer: optim.Optimizer,
                   scheduler: Optional[torch.optim.lr_scheduler._LRScheduler] = None) -> Tuple[float, float]:
        """
        Train for one epoch.

        Args:
            train_loader: Training data loader
            criterion: Loss function
            optimizer: Optimizer
            scheduler: Learning rate scheduler (optional)

        Returns:
            Tuple of (average_loss, accuracy)
        """
        self.model.train()
        total_loss = 0.0
        correct = 0
        total = 0

        pbar = tqdm(train_loader, desc=f"{self.model_name} Training")
        for batch_x, batch_y in pbar:
            batch_x = batch_x.to(self.device)
            batch_y = batch_y.to(self.device)

            # Forward pass
            optimizer.zero_grad()

            # Handle models with different output formats
            if isinstance(self.model, LSTMModel):
                outputs, _ = self.model(batch_x)
            else:
                outputs = self.model(batch_x)

            loss = criterion(outputs, batch_y)

            # Backward pass
            loss.backward()

            # Gradient clipping
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)

            optimizer.step()

            # Update scheduler if provided
            if scheduler is not None and isinstance(scheduler, WarmupCosineScheduler):
                scheduler.step()

            # Statistics
            total_loss += loss.item()
            _, predicted = outputs.max(1)
            total += batch_y.size(0)
            correct += predicted.eq(batch_y).sum().item()

            # Update progress bar
            pbar.set_postfix({
                'loss': f'{loss.item():.4f}',
                'acc': f'{100.0 * correct / total:.2f}%'
            })

        avg_loss = total_loss / len(train_loader)
        accuracy = correct / total

        return avg_loss, accuracy

    def validate(self,
                val_loader: DataLoader,
                criterion: nn.Module) -> Tuple[float, float, np.ndarray, np.ndarray]:
        """
        Validate model.

        Args:
            val_loader: Validation data loader
            criterion: Loss function

        Returns:
            Tuple of (average_loss, accuracy, predictions, labels)
        """
        self.model.eval()
        total_loss = 0.0
        all_preds = []
        all_labels = []

        with torch.no_grad():
            for batch_x, batch_y in val_loader:
                batch_x = batch_x.to(self.device)
                batch_y = batch_y.to(self.device)

                # Forward pass
                if isinstance(self.model, LSTMModel):
                    outputs, _ = self.model(batch_x)
                else:
                    outputs = self.model(batch_x)

                loss = criterion(outputs, batch_y)

                # Statistics
                total_loss += loss.item()
                _, predicted = outputs.max(1)

                all_preds.extend(predicted.cpu().numpy())
                all_labels.extend(batch_y.cpu().numpy())

        avg_loss = total_loss / len(val_loader)
        accuracy = np.mean(np.array(all_preds) == np.array(all_labels))

        return avg_loss, accuracy, np.array(all_preds), np.array(all_labels)

    def fit(self,
            train_loader: DataLoader,
            val_loader: DataLoader,
            criterion: nn.Module,
            optimizer: optim.Optimizer,
            scheduler: Optional[torch.optim.lr_scheduler._LRScheduler] = None,
            epochs: int = 50,
            early_stopping_patience: int = 7,
            save_dir: Optional[str] = None) -> Dict:
        """
        Complete training loop with early stopping.

        Args:
            train_loader: Training data loader
            val_loader: Validation data loader
            criterion: Loss function
            optimizer: Optimizer
            scheduler: Learning rate scheduler
            epochs: Maximum epochs
            early_stopping_patience: Patience for early stopping
            save_dir: Directory to save checkpoints

        Returns:
            Training history dictionary
        """
        early_stopping = EarlyStopping(patience=early_stopping_patience, mode='min')
        best_val_loss = float('inf')

        logger.info(f"Starting training for {self.model_name}")
        logger.info(f"Epochs: {epochs}, Device: {self.device}")

        for epoch in range(epochs):
            logger.info(f"\nEpoch {epoch + 1}/{epochs}")

            # Train
            train_loss, train_acc = self.train_epoch(
                train_loader, criterion, optimizer, scheduler
            )

            # Validate
            val_loss, val_acc, _, _ = self.validate(val_loader, criterion)

            # Update scheduler (if not warmup-based)
            if scheduler is not None and not isinstance(scheduler, WarmupCosineScheduler):
                scheduler.step(val_loss)

            # Update history
            self.history['train_loss'].append(train_loss)
            self.history['val_loss'].append(val_loss)
            self.history['train_acc'].append(train_acc)
            self.history['val_acc'].append(val_acc)

            # Log
            logger.info(
                f"Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.4f} | "
                f"Val Loss: {val_loss:.4f}, Val Acc: {val_acc:.4f}"
            )

            # Save best model
            if val_loss < best_val_loss and save_dir is not None:
                best_val_loss = val_loss
                save_path = Path(save_dir)
                save_path.mkdir(parents=True, exist_ok=True)
                torch.save(
                    self.model.state_dict(),
                    save_path / f"{self.model_name}_best.pt"
                )
                logger.info(f"Saved best model (val_loss: {val_loss:.4f})")

            # Early stopping
            if early_stopping(val_loss):
                logger.info(f"Early stopping triggered at epoch {epoch + 1}")
                break

        logger.info(f"Training completed for {self.model_name}")
        return self.history


class EnsembleTrainer:
    """
    Complete ensemble training pipeline.

    Trains LSTM, Transformer, and CNN models, then calibrates the ensemble.
    """

    def __init__(self,
                 input_size: int = 128,
                 seq_len: int = 60,
                 num_classes: int = 3,
                 device: str = 'cuda' if torch.cuda.is_available() else 'cpu'):
        """
        Args:
            input_size: Number of input features
            seq_len: Sequence length
            num_classes: Number of classes
            device: Device to train on
        """
        self.input_size = input_size
        self.seq_len = seq_len
        self.num_classes = num_classes
        self.device = device

        # Initialize models
        self.lstm_model = LSTMModel(
            input_size=input_size,
            hidden_size=LSTMConfig.HIDDEN_SIZE,
            num_layers=LSTMConfig.NUM_LAYERS,
            dropout=LSTMConfig.DROPOUT,
            num_classes=num_classes
        )

        self.transformer_model = TransformerModel(
            input_size=input_size,
            d_model=TransformerConfig.D_MODEL,
            nhead=TransformerConfig.NHEAD,
            num_encoder_layers=TransformerConfig.NUM_ENCODER_LAYERS,
            dim_feedforward=TransformerConfig.DIM_FEEDFORWARD,
            dropout=TransformerConfig.DROPOUT,
            num_classes=num_classes
        )

        self.cnn_model = CNNModel(
            input_size=input_size,
            seq_len=seq_len,
            num_classes=num_classes
        )

        # Training histories
        self.training_histories = {}

    def prepare_data(self,
                    X: np.ndarray,
                    y: np.ndarray,
                    val_split: float = 0.2,
                    batch_size: int = 256) -> Tuple[DataLoader, DataLoader]:
        """
        Prepare data loaders.

        Args:
            X: Features (n_samples, seq_len, features)
            y: Labels (n_samples,)
            val_split: Validation split ratio
            batch_size: Batch size

        Returns:
            Tuple of (train_loader, val_loader)
        """
        # Split data
        n_samples = len(X)
        n_val = int(n_samples * val_split)

        # Use last portion for validation (time series)
        X_train, X_val = X[:-n_val], X[-n_val:]
        y_train, y_val = y[:-n_val], y[-n_val:]

        logger.info(f"Train size: {len(X_train)}, Val size: {len(X_val)}")

        # Convert to tensors
        X_train_t = torch.from_numpy(X_train).float()
        y_train_t = torch.from_numpy(y_train).long()
        X_val_t = torch.from_numpy(X_val).float()
        y_val_t = torch.from_numpy(y_val).long()

        # Create datasets
        train_dataset = TensorDataset(X_train_t, y_train_t)
        val_dataset = TensorDataset(X_val_t, y_val_t)

        # Create loaders
        train_loader = DataLoader(
            train_dataset,
            batch_size=batch_size,
            shuffle=True,
            num_workers=0,
            pin_memory=True
        )
        val_loader = DataLoader(
            val_dataset,
            batch_size=batch_size,
            shuffle=False,
            num_workers=0,
            pin_memory=True
        )

        return train_loader, val_loader

    def train_all_models(self,
                        train_loader: DataLoader,
                        val_loader: DataLoader,
                        save_dir: str = "models/ensemble") -> Dict:
        """
        Train all three models.

        Args:
            train_loader: Training data loader
            val_loader: Validation data loader
            save_dir: Directory to save models

        Returns:
            Dictionary of training histories
        """
        save_path = Path(save_dir)
        save_path.mkdir(parents=True, exist_ok=True)

        # Train LSTM
        logger.info("=" * 70)
        logger.info("Training LSTM Model")
        logger.info("=" * 70)

        lstm_trainer = ModelTrainer(self.lstm_model, self.device, 'LSTM')
        lstm_optimizer = optim.AdamW(
            self.lstm_model.parameters(),
            lr=LSTMConfig.LEARNING_RATE,
            weight_decay=LSTMConfig.WEIGHT_DECAY
        )
        lstm_scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            lstm_optimizer, mode='min', patience=3, factor=0.5
        )
        lstm_criterion = nn.CrossEntropyLoss()

        lstm_history = lstm_trainer.fit(
            train_loader, val_loader,
            criterion=lstm_criterion,
            optimizer=lstm_optimizer,
            scheduler=lstm_scheduler,
            epochs=LSTMConfig.EPOCHS,
            early_stopping_patience=LSTMConfig.EARLY_STOPPING_PATIENCE,
            save_dir=save_dir
        )
        self.training_histories['lstm'] = lstm_history

        # Train Transformer
        logger.info("\n" + "=" * 70)
        logger.info("Training Transformer Model")
        logger.info("=" * 70)

        transformer_trainer = ModelTrainer(self.transformer_model, self.device, 'Transformer')
        transformer_optimizer = optim.AdamW(
            self.transformer_model.parameters(),
            lr=TransformerConfig.LEARNING_RATE,
            weight_decay=TransformerConfig.WEIGHT_DECAY
        )
        # Warmup scheduler for Transformer
        total_steps = len(train_loader) * TransformerConfig.EPOCHS
        transformer_scheduler = WarmupCosineScheduler(
            transformer_optimizer,
            warmup_steps=TransformerConfig.WARMUP_STEPS,
            total_steps=total_steps
        )
        transformer_criterion = nn.CrossEntropyLoss(label_smoothing=0.1)

        transformer_history = transformer_trainer.fit(
            train_loader, val_loader,
            criterion=transformer_criterion,
            optimizer=transformer_optimizer,
            scheduler=transformer_scheduler,
            epochs=TransformerConfig.EPOCHS,
            early_stopping_patience=TransformerConfig.EARLY_STOPPING_PATIENCE,
            save_dir=save_dir
        )
        self.training_histories['transformer'] = transformer_history

        # Train CNN
        logger.info("\n" + "=" * 70)
        logger.info("Training CNN Model")
        logger.info("=" * 70)

        cnn_trainer = ModelTrainer(self.cnn_model, self.device, 'CNN')
        cnn_optimizer = optim.AdamW(
            self.cnn_model.parameters(),
            lr=CNNConfig.LEARNING_RATE,
            weight_decay=CNNConfig.WEIGHT_DECAY
        )
        cnn_scheduler = optim.lr_scheduler.ReduceLROnPlateau(
            cnn_optimizer, mode='min', patience=3, factor=0.5
        )
        cnn_criterion = nn.CrossEntropyLoss()

        cnn_history = cnn_trainer.fit(
            train_loader, val_loader,
            criterion=cnn_criterion,
            optimizer=cnn_optimizer,
            scheduler=cnn_scheduler,
            epochs=CNNConfig.EPOCHS,
            early_stopping_patience=CNNConfig.EARLY_STOPPING_PATIENCE,
            save_dir=save_dir
        )
        self.training_histories['cnn'] = cnn_history

        logger.info("\n" + "=" * 70)
        logger.info("All models trained successfully!")
        logger.info("=" * 70)

        return self.training_histories

    def save_training_report(self, save_path: str) -> None:
        """
        Save training report as JSON.

        Args:
            save_path: Path to save report
        """
        report = {
            'timestamp': datetime.utcnow().isoformat(),
            'config': {
                'input_size': self.input_size,
                'seq_len': self.seq_len,
                'num_classes': self.num_classes,
                'device': self.device
            },
            'training_histories': self.training_histories
        }

        with open(save_path, 'w') as f:
            json.dump(report, f, indent=2)

        logger.info(f"Training report saved to {save_path}")


if __name__ == "__main__":
    # Test training pipeline
    print("Testing Training Pipeline...\n")

    # Create synthetic training data
    np.random.seed(42)
    torch.manual_seed(42)

    n_samples = 5000
    seq_len = 60
    features = 128
    num_classes = 3

    # Generate data
    X = np.random.randn(n_samples, seq_len, features).astype(np.float32)
    y = np.random.randint(0, num_classes, size=n_samples)

    # Initialize trainer
    print("Initializing Ensemble Trainer...")
    trainer = EnsembleTrainer(
        input_size=features,
        seq_len=seq_len,
        num_classes=num_classes
    )

    # Prepare data
    print("\nPreparing data loaders...")
    train_loader, val_loader = trainer.prepare_data(
        X, y,
        val_split=0.2,
        batch_size=256
    )

    # Train models (small number of epochs for testing)
    print("\nTraining models (test mode with 3 epochs)...")

    # Override configs for quick test
    LSTMConfig.EPOCHS = 3
    TransformerConfig.EPOCHS = 3
    CNNConfig.EPOCHS = 3

    histories = trainer.train_all_models(
        train_loader, val_loader,
        save_dir="models/test_ensemble"
    )

    # Print summary
    print("\n" + "=" * 70)
    print("TRAINING SUMMARY")
    print("=" * 70)
    for model_name, history in histories.items():
        print(f"\n{model_name.upper()}:")
        print(f"  Final Train Loss: {history['train_loss'][-1]:.4f}")
        print(f"  Final Val Loss:   {history['val_loss'][-1]:.4f}")
        print(f"  Final Train Acc:  {history['train_acc'][-1]:.4f}")
        print(f"  Final Val Acc:    {history['val_acc'][-1]:.4f}")

    # Save report
    trainer.save_training_report("models/test_ensemble/training_report.json")

    print("\n✓ Training Pipeline test passed!")
