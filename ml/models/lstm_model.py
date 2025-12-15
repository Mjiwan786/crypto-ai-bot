"""
LSTM Model Architecture for Crypto Trading Signal Prediction.

Bidirectional LSTM with attention mechanism for capturing temporal dependencies.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


class LSTMModel(nn.Module):
    """
    Bidirectional LSTM with Multi-Head Attention.

    Architecture:
        - Bidirectional LSTM (3 layers, 256 hidden units)
        - Multi-head attention (8 heads)
        - Fully connected layers with batch normalization
        - Output: 3 classes (SHORT, NEUTRAL, LONG)
    """

    def __init__(self,
                 input_size: int = 128,
                 hidden_size: int = 256,
                 num_layers: int = 3,
                 dropout: float = 0.3,
                 num_classes: int = 3):
        """
        Args:
            input_size: Number of input features (default 128)
            hidden_size: LSTM hidden units (default 256)
            num_layers: Number of LSTM layers (default 3)
            dropout: Dropout rate (default 0.3)
            num_classes: Output classes (default 3: SHORT, NEUTRAL, LONG)
        """
        super(LSTMModel, self).__init__()

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.num_classes = num_classes

        # Bidirectional LSTM layers
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0,
            batch_first=True,
            bidirectional=True  # Bidirectional for better context
        )

        # Multi-head attention
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size * 2,  # *2 for bidirectional
            num_heads=8,
            dropout=0.1,
            batch_first=True
        )

        # Layer normalization
        self.layer_norm = nn.LayerNorm(hidden_size * 2)

        # Fully connected layers
        self.fc1 = nn.Linear(hidden_size * 2, 128)
        self.bn1 = nn.BatchNorm1d(128)
        self.dropout1 = nn.Dropout(dropout)

        self.fc2 = nn.Linear(128, 64)
        self.bn2 = nn.BatchNorm1d(64)
        self.dropout2 = nn.Dropout(dropout * 0.67)  # Reduced dropout

        # Output layer
        self.fc_out = nn.Linear(64, num_classes)

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Initialize model weights with Xavier initialization."""
        for name, param in self.named_parameters():
            if 'weight_ih' in name:
                nn.init.xavier_uniform_(param.data)
            elif 'weight_hh' in name:
                nn.init.orthogonal_(param.data)
            elif 'bias' in name:
                param.data.fill_(0)
            elif 'fc' in name and 'weight' in name:
                nn.init.xavier_uniform_(param.data)

    def forward(self, x):
        """
        Forward pass.

        Args:
            x: Input tensor of shape (batch, seq_len, features)

        Returns:
            Tuple of (logits, attention_weights)
                logits: (batch, num_classes)
                attention_weights: (batch, seq_len, seq_len)
        """
        batch_size, seq_len, features = x.size()

        # LSTM forward pass
        lstm_out, (h_n, c_n) = self.lstm(x)
        # lstm_out shape: (batch, seq_len, hidden_size*2)

        # Layer normalization
        lstm_out = self.layer_norm(lstm_out)

        # Multi-head attention
        attn_out, attn_weights = self.attention(
            lstm_out, lstm_out, lstm_out
        )
        # attn_out shape: (batch, seq_len, hidden_size*2)

        # Take last timestep output
        last_out = attn_out[:, -1, :]

        # Fully connected layers
        x = F.relu(self.bn1(self.fc1(last_out)))
        x = self.dropout1(x)

        x = F.relu(self.bn2(self.fc2(x)))
        x = self.dropout2(x)

        # Output logits
        logits = self.fc_out(x)

        return logits, attn_weights

    def predict_proba(self, x):
        """
        Predict probabilities.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            Probabilities (batch, num_classes)
        """
        self.eval()
        with torch.no_grad():
            logits, _ = self.forward(x)
            probabilities = F.softmax(logits, dim=-1)
        return probabilities

    def get_feature_importance(self, x, target_class: int = None):
        """
        Get feature importance using gradient-based attribution.

        Args:
            x: Input tensor (batch, seq_len, features)
            target_class: Target class for attribution (default: predicted class)

        Returns:
            Feature importance scores (features,)
        """
        self.eval()
        x.requires_grad = True

        # Forward pass
        logits, _ = self.forward(x)

        if target_class is None:
            target_class = logits.argmax(dim=-1)

        # Backward pass for gradient
        self.zero_grad()
        logits[0, target_class].backward()

        # Gradient importance (absolute values)
        importance = x.grad.abs().mean(dim=(0, 1)).cpu().numpy()

        return importance


class LSTMConfig:
    """Configuration for LSTM model."""
    INPUT_SIZE = 128
    HIDDEN_SIZE = 256
    NUM_LAYERS = 3
    DROPOUT = 0.3
    NUM_CLASSES = 3
    LEARNING_RATE = 0.001
    WEIGHT_DECAY = 1e-5
    BATCH_SIZE = 256
    EPOCHS = 50
    EARLY_STOPPING_PATIENCE = 7


if __name__ == "__main__":
    # Test model
    print("Testing LSTM model...")

    # Create sample data
    batch_size = 32
    seq_len = 60
    features = 128

    x = torch.randn(batch_size, seq_len, features)

    # Initialize model
    model = LSTMModel(
        input_size=features,
        hidden_size=256,
        num_layers=3,
        dropout=0.3
    )

    # Forward pass
    logits, attn_weights = model(x)

    print(f"Input shape: {x.shape}")
    print(f"Output logits shape: {logits.shape}")
    print(f"Attention weights shape: {attn_weights.shape}")

    # Predict probabilities
    probs = model.predict_proba(x)
    print(f"Probabilities shape: {probs.shape}")
    print(f"Sample probabilities:\n{probs[:3]}")

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    print(f"\nModel parameters:")
    print(f"  Total: {total_params:,}")
    print(f"  Trainable: {trainable_params:,}")
    print(f"\n✓ LSTM model test passed!")
