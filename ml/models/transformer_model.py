"""
Transformer Model Architecture for Crypto Trading Signal Prediction.

Multi-head attention Transformer encoder for learning cross-feature relationships.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import math


class PositionalEncoding(nn.Module):
    """
    Positional encoding for Transformer.

    Adds sinusoidal position embeddings to input sequences to preserve
    temporal ordering information.
    """

    def __init__(self, d_model: int, dropout: float = 0.1, max_len: int = 5000):
        """
        Args:
            d_model: Embedding dimension
            dropout: Dropout rate
            max_len: Maximum sequence length
        """
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        # Create positional encoding matrix
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(
            torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model)
        )

        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)  # Shape: (1, max_len, d_model)

        self.register_buffer('pe', pe)

    def forward(self, x):
        """
        Add positional encoding to input.

        Args:
            x: Input tensor (batch, seq_len, d_model)

        Returns:
            Tensor with positional encoding added
        """
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)


class TransformerModel(nn.Module):
    """
    Transformer Encoder for trading signal prediction.

    Architecture:
        - Input projection layer
        - Positional encoding
        - 6-layer Transformer encoder
        - Multi-scale pooling (avg + max)
        - Fully connected classifier head
    """

    def __init__(self,
                 input_size: int = 128,
                 d_model: int = 512,
                 nhead: int = 8,
                 num_encoder_layers: int = 6,
                 dim_feedforward: int = 2048,
                 dropout: float = 0.1,
                 num_classes: int = 3):
        """
        Args:
            input_size: Number of input features (default 128)
            d_model: Embedding dimension (default 512)
            nhead: Number of attention heads (default 8)
            num_encoder_layers: Number of encoder layers (default 6)
            dim_feedforward: Feedforward network dimension (default 2048)
            dropout: Dropout rate (default 0.1)
            num_classes: Output classes (default 3)
        """
        super(TransformerModel, self).__init__()

        self.input_size = input_size
        self.d_model = d_model
        self.nhead = nhead
        self.num_classes = num_classes

        # Input projection (project features to d_model)
        self.input_projection = nn.Linear(input_size, d_model)

        # Positional encoding
        self.pos_encoder = PositionalEncoding(d_model, dropout)

        # Transformer encoder layers
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation='gelu',  # GELU activation (better than ReLU)
            batch_first=True,
            norm_first=True  # Pre-LayerNorm (more stable)
        )

        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=num_encoder_layers,
            norm=nn.LayerNorm(d_model)
        )

        # Multi-scale pooling
        self.avg_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)

        # Classifier head
        self.fc1 = nn.Linear(d_model * 2, 256)  # *2 for avg+max pooling
        self.bn1 = nn.BatchNorm1d(256)
        self.dropout1 = nn.Dropout(0.3)

        self.fc2 = nn.Linear(256, 128)
        self.bn2 = nn.BatchNorm1d(128)
        self.dropout2 = nn.Dropout(0.2)

        self.fc_out = nn.Linear(128, num_classes)

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Initialize weights with Xavier uniform initialization."""
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(self, x, src_mask=None):
        """
        Forward pass.

        Args:
            x: Input tensor (batch, seq_len, features)
            src_mask: Optional attention mask

        Returns:
            Logits (batch, num_classes)
        """
        batch_size, seq_len, features = x.size()

        # Project input to d_model dimension
        x = self.input_projection(x)
        # x shape: (batch, seq_len, d_model)

        # Add positional encoding
        x = self.pos_encoder(x)

        # Transformer encoding
        encoded = self.transformer_encoder(x, mask=src_mask)
        # encoded shape: (batch, seq_len, d_model)

        # Multi-scale pooling
        encoded_t = encoded.transpose(1, 2)  # (batch, d_model, seq_len)
        avg_pooled = self.avg_pool(encoded_t).squeeze(-1)  # (batch, d_model)
        max_pooled = self.max_pool(encoded_t).squeeze(-1)  # (batch, d_model)

        # Concatenate pooled representations
        pooled = torch.cat([avg_pooled, max_pooled], dim=1)  # (batch, d_model*2)

        # Fully connected layers
        x = F.relu(self.bn1(self.fc1(pooled)))
        x = self.dropout1(x)

        x = F.relu(self.bn2(self.fc2(x)))
        x = self.dropout2(x)

        # Output logits
        logits = self.fc_out(x)

        return logits

    def predict_proba(self, x):
        """
        Predict class probabilities.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            Probabilities (batch, num_classes)
        """
        self.eval()
        with torch.no_grad():
            logits = self.forward(x)
            probabilities = F.softmax(logits, dim=-1)
        return probabilities

    def get_attention_maps(self, x):
        """
        Extract attention maps from all encoder layers.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            List of attention maps from each layer
        """
        self.eval()
        attention_maps = []

        # Forward pass with attention extraction
        x = self.input_projection(x)
        x = self.pos_encoder(x)

        for layer in self.transformer_encoder.layers:
            # Self-attention
            attn_output, attn_weights = layer.self_attn(
                x, x, x,
                need_weights=True,
                average_attn_weights=False
            )
            attention_maps.append(attn_weights.detach())
            x = layer(x)

        return attention_maps


class TransformerConfig:
    """Configuration for Transformer model."""
    INPUT_SIZE = 128
    D_MODEL = 512
    NHEAD = 8
    NUM_ENCODER_LAYERS = 6
    DIM_FEEDFORWARD = 2048
    DROPOUT = 0.1
    NUM_CLASSES = 3
    LEARNING_RATE = 0.0001
    WEIGHT_DECAY = 1e-4
    BATCH_SIZE = 128
    EPOCHS = 100
    WARMUP_STEPS = 1000
    EARLY_STOPPING_PATIENCE = 10


class WarmupCosineScheduler:
    """
    Learning rate scheduler with linear warmup and cosine annealing.

    Used for Transformer training stability.
    """

    def __init__(self, optimizer, warmup_steps: int, total_steps: int,
                 min_lr: float = 1e-6):
        """
        Args:
            optimizer: PyTorch optimizer
            warmup_steps: Number of warmup steps
            total_steps: Total training steps
            min_lr: Minimum learning rate
        """
        self.optimizer = optimizer
        self.warmup_steps = warmup_steps
        self.total_steps = total_steps
        self.min_lr = min_lr
        self.base_lr = optimizer.param_groups[0]['lr']
        self.current_step = 0

    def step(self):
        """Update learning rate."""
        self.current_step += 1

        if self.current_step < self.warmup_steps:
            # Linear warmup
            lr = self.base_lr * (self.current_step / self.warmup_steps)
        else:
            # Cosine annealing
            progress = (self.current_step - self.warmup_steps) / (
                self.total_steps - self.warmup_steps
            )
            lr = self.min_lr + (self.base_lr - self.min_lr) * 0.5 * (
                1 + math.cos(math.pi * progress)
            )

        for param_group in self.optimizer.param_groups:
            param_group['lr'] = lr

        return lr


if __name__ == "__main__":
    # Test model
    print("Testing Transformer model...")

    # Create sample data
    batch_size = 32
    seq_len = 60
    features = 128

    x = torch.randn(batch_size, seq_len, features)

    # Initialize model
    model = TransformerModel(
        input_size=features,
        d_model=512,
        nhead=8,
        num_encoder_layers=6,
        dim_feedforward=2048,
        dropout=0.1
    )

    # Forward pass
    logits = model(x)

    print(f"Input shape: {x.shape}")
    print(f"Output logits shape: {logits.shape}")

    # Predict probabilities
    probs = model.predict_proba(x)
    print(f"Probabilities shape: {probs.shape}")
    print(f"Sample probabilities:\n{probs[:3]}")

    # Test attention maps
    attention_maps = model.get_attention_maps(x)
    print(f"\nAttention maps from {len(attention_maps)} layers")
    print(f"Each attention map shape: {attention_maps[0].shape}")

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    print(f"\nModel parameters:")
    print(f"  Total: {total_params:,}")
    print(f"  Trainable: {trainable_params:,}")

    # Test learning rate scheduler
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0001)
    scheduler = WarmupCosineScheduler(
        optimizer,
        warmup_steps=1000,
        total_steps=10000
    )

    print(f"\nLearning rate schedule:")
    lrs = []
    for step in range(10000):
        lr = scheduler.step()
        if step % 1000 == 0:
            lrs.append(lr)
            print(f"  Step {step:5d}: LR = {lr:.6f}")

    print(f"\n✓ Transformer model test passed!")
