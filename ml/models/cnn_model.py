"""
CNN Model Architecture for Crypto Trading Signal Prediction.

1D Convolutional Neural Network with Inception modules for pattern recognition.

Author: AI Architecture Team
Version: 1.0.0
Date: 2025-11-17
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np


class InceptionModule(nn.Module):
    """
    Inception module for multi-scale feature extraction.

    Applies convolutions with different kernel sizes in parallel to capture
    patterns at multiple scales, then concatenates the results.
    """

    def __init__(self, in_channels: int, out_channels_list: list):
        """
        Args:
            in_channels: Number of input channels
            out_channels_list: List of output channels for each path
                              [1x1, 3x3, 5x5, pool]
        """
        super(InceptionModule, self).__init__()

        # 1x1 convolution path
        self.conv1x1 = nn.Conv1d(
            in_channels, out_channels_list[0], kernel_size=1
        )

        # 3x3 convolution path (with 1x1 bottleneck)
        self.conv3x3 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_list[1], kernel_size=1),
            nn.BatchNorm1d(out_channels_list[1]),
            nn.ReLU(inplace=True),
            nn.Conv1d(out_channels_list[1], out_channels_list[1],
                     kernel_size=3, padding=1)
        )

        # 5x5 convolution path (with 1x1 bottleneck)
        self.conv5x5 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_list[2], kernel_size=1),
            nn.BatchNorm1d(out_channels_list[2]),
            nn.ReLU(inplace=True),
            nn.Conv1d(out_channels_list[2], out_channels_list[2],
                     kernel_size=5, padding=2)
        )

        # Max pooling path (with 1x1 projection)
        self.pool_path = nn.Sequential(
            nn.MaxPool1d(kernel_size=3, stride=1, padding=1),
            nn.Conv1d(in_channels, out_channels_list[3], kernel_size=1)
        )

        # Batch normalization after concatenation
        total_out_channels = sum(out_channels_list)
        self.bn = nn.BatchNorm1d(total_out_channels)

    def forward(self, x):
        """
        Forward pass through inception module.

        Args:
            x: Input tensor (batch, channels, seq_len)

        Returns:
            Concatenated multi-scale features
        """
        out1 = self.conv1x1(x)
        out2 = self.conv3x3(x)
        out3 = self.conv5x5(x)
        out4 = self.pool_path(x)

        # Concatenate along channel dimension
        out = torch.cat([out1, out2, out3, out4], dim=1)
        out = self.bn(out)

        return F.relu(out)


class CNNModel(nn.Module):
    """
    1D CNN with Inception modules for trading signal prediction.

    Architecture:
        - Multi-scale 1D convolutions (3, 5, 7 kernel sizes)
        - 2 Inception modules
        - Global average + max pooling
        - Fully connected classifier head
    """

    def __init__(self,
                 input_size: int = 128,
                 seq_len: int = 60,
                 num_classes: int = 3):
        """
        Args:
            input_size: Number of input features (default 128)
            seq_len: Sequence length (default 60)
            num_classes: Output classes (default 3)
        """
        super(CNNModel, self).__init__()

        self.input_size = input_size
        self.seq_len = seq_len
        self.num_classes = num_classes

        # Initial convolution layers (multi-scale)
        self.conv1 = nn.Conv1d(input_size, 128, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(128)

        self.conv2 = nn.Conv1d(128, 256, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm1d(256)

        self.conv3 = nn.Conv1d(256, 256, kernel_size=7, padding=3)
        self.bn3 = nn.BatchNorm1d(256)

        # Inception modules (multi-scale feature extraction)
        self.inception1 = InceptionModule(256, [64, 64, 64, 64])  # Total: 256 channels
        self.inception2 = InceptionModule(256, [64, 64, 64, 64])  # Total: 256 channels

        # Global pooling
        self.global_avg_pool = nn.AdaptiveAvgPool1d(1)
        self.global_max_pool = nn.AdaptiveMaxPool1d(1)

        # Fully connected classifier head
        self.fc1 = nn.Linear(512, 256)  # 256*2 from avg+max pooling
        self.bn_fc1 = nn.BatchNorm1d(256)
        self.dropout1 = nn.Dropout(0.3)

        self.fc2 = nn.Linear(256, 128)
        self.bn_fc2 = nn.BatchNorm1d(128)
        self.dropout2 = nn.Dropout(0.2)

        self.fc_out = nn.Linear(128, num_classes)

        # Initialize weights
        self._init_weights()

    def _init_weights(self):
        """Initialize weights with Kaiming initialization (good for ReLU)."""
        for m in self.modules():
            if isinstance(m, nn.Conv1d):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.BatchNorm1d):
                nn.init.constant_(m.weight, 1)
                nn.init.constant_(m.bias, 0)
            elif isinstance(m, nn.Linear):
                nn.init.kaiming_normal_(m.weight, mode='fan_out', nonlinearity='relu')
                if m.bias is not None:
                    nn.init.constant_(m.bias, 0)

    def forward(self, x):
        """
        Forward pass.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            Logits (batch, num_classes)
        """
        batch_size, seq_len, features = x.size()

        # Transpose for Conv1d: (batch, features, seq_len)
        x = x.transpose(1, 2)

        # Initial convolution layers
        x = F.relu(self.bn1(self.conv1(x)))
        x = F.relu(self.bn2(self.conv2(x)))
        x = F.relu(self.bn3(self.conv3(x)))

        # Inception modules
        x = self.inception1(x)
        x = self.inception2(x)

        # Global pooling (reduce seq_len dimension)
        avg_pooled = self.global_avg_pool(x).squeeze(-1)  # (batch, 256)
        max_pooled = self.global_max_pool(x).squeeze(-1)  # (batch, 256)

        # Concatenate pooled representations
        pooled = torch.cat([avg_pooled, max_pooled], dim=1)  # (batch, 512)

        # Fully connected layers
        x = F.relu(self.bn_fc1(self.fc1(pooled)))
        x = self.dropout1(x)

        x = F.relu(self.bn_fc2(self.fc2(x)))
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

    def extract_features(self, x):
        """
        Extract learned features from the model.

        Args:
            x: Input tensor (batch, seq_len, features)

        Returns:
            Feature tensor before final classification (batch, 128)
        """
        self.eval()
        with torch.no_grad():
            # Transpose for Conv1d
            x = x.transpose(1, 2)

            # Conv layers
            x = F.relu(self.bn1(self.conv1(x)))
            x = F.relu(self.bn2(self.conv2(x)))
            x = F.relu(self.bn3(self.conv3(x)))

            # Inception modules
            x = self.inception1(x)
            x = self.inception2(x)

            # Global pooling
            avg_pooled = self.global_avg_pool(x).squeeze(-1)
            max_pooled = self.global_max_pool(x).squeeze(-1)
            pooled = torch.cat([avg_pooled, max_pooled], dim=1)

            # FC layers (except final)
            x = F.relu(self.bn_fc1(self.fc1(pooled)))
            x = F.relu(self.bn_fc2(self.fc2(x)))

        return x


class CNNConfig:
    """Configuration for CNN model."""
    INPUT_SIZE = 128
    SEQ_LEN = 60
    NUM_CLASSES = 3
    LEARNING_RATE = 0.001
    WEIGHT_DECAY = 1e-5
    BATCH_SIZE = 256
    EPOCHS = 50
    EARLY_STOPPING_PATIENCE = 7


class TimeSeriesAugmentation:
    """
    Data augmentation for time-series data.

    Techniques:
    - Time warping: Stretch/compress time axis
    - Magnitude warping: Scale amplitude
    - Window slicing: Random cropping
    """

    @staticmethod
    def time_warp(x, sigma=0.2):
        """
        Time warping: randomly warp time steps.

        Args:
            x: Input tensor (batch, seq_len, features)
            sigma: Warping strength

        Returns:
            Time-warped tensor
        """
        batch_size, seq_len, features = x.size()

        # Generate smooth random warping curve
        warp = np.random.randn(seq_len) * sigma
        warp = np.cumsum(warp)
        warp = (warp - warp.min()) / (warp.max() - warp.min()) * (seq_len - 1)

        # Interpolate
        x_warped = torch.zeros_like(x)
        for b in range(batch_size):
            for f in range(features):
                x_warped[b, :, f] = torch.tensor(
                    np.interp(warp, np.arange(seq_len), x[b, :, f].numpy()),
                    dtype=x.dtype
                )

        return x_warped

    @staticmethod
    def magnitude_warp(x, sigma=0.2):
        """
        Magnitude warping: randomly scale amplitude.

        Args:
            x: Input tensor (batch, seq_len, features)
            sigma: Warping strength

        Returns:
            Magnitude-warped tensor
        """
        batch_size, seq_len, features = x.size()

        # Generate smooth random scaling curve
        scale = 1 + np.random.randn(seq_len) * sigma
        scale = np.maximum(scale, 0.1)  # Avoid too small values

        # Apply scaling
        x_warped = x * torch.tensor(scale, dtype=x.dtype).unsqueeze(0).unsqueeze(2)

        return x_warped

    @staticmethod
    def window_slice(x, slice_ratio=0.9):
        """
        Window slicing: random cropping and resizing.

        Args:
            x: Input tensor (batch, seq_len, features)
            slice_ratio: Ratio of sequence to keep (default 0.9)

        Returns:
            Sliced and resized tensor
        """
        batch_size, seq_len, features = x.size()

        slice_len = int(seq_len * slice_ratio)
        start = np.random.randint(0, seq_len - slice_len + 1)

        # Slice
        x_sliced = x[:, start:start+slice_len, :]

        # Resize back to original length (linear interpolation)
        x_resized = F.interpolate(
            x_sliced.transpose(1, 2),
            size=seq_len,
            mode='linear',
            align_corners=False
        ).transpose(1, 2)

        return x_resized


if __name__ == "__main__":
    # Test model
    print("Testing CNN model...")

    # Create sample data
    batch_size = 32
    seq_len = 60
    features = 128

    x = torch.randn(batch_size, seq_len, features)

    # Initialize model
    model = CNNModel(
        input_size=features,
        seq_len=seq_len,
        num_classes=3
    )

    # Forward pass
    logits = model(x)

    print(f"Input shape: {x.shape}")
    print(f"Output logits shape: {logits.shape}")

    # Predict probabilities
    probs = model.predict_proba(x)
    print(f"Probabilities shape: {probs.shape}")
    print(f"Sample probabilities:\n{probs[:3]}")

    # Extract features
    features_extracted = model.extract_features(x)
    print(f"\nExtracted features shape: {features_extracted.shape}")

    # Count parameters
    total_params = sum(p.numel() for p in model.parameters())
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)

    print(f"\nModel parameters:")
    print(f"  Total: {total_params:,}")
    print(f"  Trainable: {trainable_params:,}")

    # Test data augmentation
    print(f"\n\nTesting data augmentation...")
    aug = TimeSeriesAugmentation()

    x_time_warped = aug.time_warp(x, sigma=0.2)
    x_magnitude_warped = aug.magnitude_warp(x, sigma=0.2)
    x_window_sliced = aug.window_slice(x, slice_ratio=0.9)

    print(f"Original shape:         {x.shape}")
    print(f"Time warped shape:      {x_time_warped.shape}")
    print(f"Magnitude warped shape: {x_magnitude_warped.shape}")
    print(f"Window sliced shape:    {x_window_sliced.shape}")

    print(f"\n✓ CNN model test passed!")
