# PRD-004: ML Ensemble Architecture
## LSTM + Transformer + CNN Multi-Model System

**Version:** 1.0.0
**Status:** Authoritative
**Last Updated:** 2025-11-17
**Owner:** AI Architecture & ML Engineering

---

## Executive Summary

### What This Document Covers

This PRD defines the **complete machine learning architecture** for the crypto-ai-bot signal generation system. The ensemble combines three complementary deep learning models:

1. **LSTM (Long Short-Term Memory)**: Captures temporal dependencies and sequential patterns in price movements
2. **Transformer**: Learns attention-based relationships across multiple timeframes and features
3. **CNN (Convolutional Neural Network)**: Extracts local patterns and technical indicator signatures

The ensemble is trained on **5+ years of historical data** (2019-2025), retrained **monthly**, and deployed with **confidence calibration** and **regime-adaptive weighting**.

### Key Specifications

| Component | Specification |
|-----------|--------------|
| **Training Data** | 5+ years OHLCV (2019-2025), 1-minute resolution |
| **Feature Count** | 128 features (price action, volume, order book, on-chain) |
| **Model Ensemble** | LSTM (40%) + Transformer (35%) + CNN (25%) |
| **Retraining Schedule** | Monthly (1st of month, 00:00 UTC) |
| **Inference Latency** | <100ms P95 (ensemble prediction) |
| **Confidence Calibration** | Platt scaling on validation set |
| **Model Versioning** | Git LFS + S3 (models/, versioned by date) |
| **Evaluation Metrics** | Win rate ≥60%, Sharpe ≥1.5, Max DD ≤-15% |

---

## Table of Contents

1. [Feature Engineering Pipeline](#feature-engineering-pipeline)
2. [Model Architectures](#model-architectures)
3. [Ensemble Weighting & Regime Detection](#ensemble-weighting--regime-detection)
4. [Confidence Score Calibration](#confidence-score-calibration)
5. [Training Pipeline](#training-pipeline)
6. [Evaluation & Cross-Validation](#evaluation--cross-validation)
7. [Signal Publishing to Redis](#signal-publishing-to-redis)
8. [Monthly Retraining Pipeline](#monthly-retraining-pipeline)
9. [Monitoring & Drift Detection](#monitoring--drift-detection)
10. [Implementation Modules](#implementation-modules)

---

## Feature Engineering Pipeline

### 1.1 Overview

**Goal:** Transform raw market data into 128 engineered features that capture price dynamics, volume patterns, market microstructure, and on-chain activity.

**Input Data Sources:**
- **OHLCV**: Open, High, Low, Close, Volume (1m, 5m, 15m, 1h candles)
- **Order Book**: L2 bid/ask depth (top 10 levels)
- **Trades**: Real-time trade executions (price, volume, side)
- **On-Chain** (future): Wallet balances, exchange inflows/outflows, gas fees

**Output:** Feature matrix `X` of shape `(n_samples, lookback_window, n_features)` where:
- `n_samples`: Number of training examples
- `lookback_window`: 60 candles (1 hour of 1-minute data)
- `n_features`: 128 features

### 1.2 Feature Categories

#### Category 1: Price Action Features (40 features)

**Raw Price Features (5):**
- `close`: Close price (normalized)
- `high`: High price (normalized)
- `low`: Low price (normalized)
- `open`: Open price (normalized)
- `hl_spread`: (high - low) / close

**Returns & Momentum (10):**
- `returns_1m`, `returns_5m`, `returns_15m`, `returns_1h`: Percentage returns
- `log_returns_1m`: Log returns
- `momentum_14`: 14-period momentum
- `roc_9`: 9-period Rate of Change
- `price_sma_ratio_20`: close / SMA(20)
- `price_sma_ratio_50`: close / SMA(50)
- `price_ema_ratio_12`: close / EMA(12)

**Trend Indicators (10):**
- `sma_20`, `sma_50`, `sma_200`: Simple Moving Averages
- `ema_12`, `ema_26`: Exponential Moving Averages
- `macd`: MACD line (EMA12 - EMA26)
- `macd_signal`: MACD signal line (EMA9 of MACD)
- `macd_histogram`: MACD - MACD_signal
- `adx_14`: Average Directional Index (trend strength)
- `aroon_up`, `aroon_down`: Aroon indicators

**Volatility Indicators (8):**
- `atr_14`: Average True Range (14-period)
- `bb_upper`, `bb_middle`, `bb_lower`: Bollinger Bands (20, 2σ)
- `bb_width`: (bb_upper - bb_lower) / bb_middle
- `bb_position`: (close - bb_lower) / (bb_upper - bb_lower)
- `keltner_upper`, `keltner_lower`: Keltner Channels

**Oscillators (7):**
- `rsi_14`: Relative Strength Index (14-period)
- `rsi_21`: RSI (21-period)
- `stoch_k`, `stoch_d`: Stochastic Oscillator
- `williams_r`: Williams %R
- `cci_20`: Commodity Channel Index
- `mfi_14`: Money Flow Index

#### Category 2: Volume Features (20 features)

**Volume Metrics (8):**
- `volume`: Raw volume (normalized)
- `volume_sma_20`: 20-period volume SMA
- `volume_ratio`: volume / volume_sma_20
- `volume_ema_10`: 10-period volume EMA
- `obv`: On-Balance Volume
- `obv_ema_20`: EMA of OBV
- `cmf_20`: Chaikin Money Flow (20-period)
- `vwap`: Volume Weighted Average Price

**Volume-Price Interaction (8):**
- `price_volume_trend`: PVT indicator
- `force_index_13`: Force Index (13-period)
- `ease_of_movement`: Ease of Movement
- `volume_price_trend`: Close change × volume
- `ad_line`: Accumulation/Distribution Line
- `buying_pressure`: (close - low) / (high - low) × volume
- `selling_pressure`: (high - close) / (high - low) × volume
- `buy_sell_ratio`: buying_pressure / selling_pressure

**Advanced Volume (4):**
- `vwap_distance`: (close - vwap) / vwap
- `volume_profile_top`: Price level with max volume in window
- `volume_delta`: Cumulative buy volume - sell volume
- `large_trade_count`: Count of trades > 2× average size

#### Category 3: Order Book Features (30 features)

**Depth Metrics (10):**
- `bid_depth_1` to `bid_depth_10`: Cumulative bid size at levels 1-10
- `ask_depth_1` to `ask_depth_10`: Cumulative ask size at levels 1-10
- `total_bid_depth`: Sum of all bid levels
- `total_ask_depth`: Sum of all ask levels
- `depth_imbalance`: (total_bid_depth - total_ask_depth) / (total_bid_depth + total_ask_depth)

**Spread Metrics (5):**
- `bid_ask_spread`: (ask_1 - bid_1) / mid_price
- `effective_spread`: 2 × |trade_price - mid_price| / mid_price
- `quoted_spread`: bid_ask_spread
- `realized_spread`: Spread after execution
- `spread_volatility`: Rolling std of spread

**Order Book Pressure (10):**
- `bid_pressure`: bid_depth_1 / (bid_depth_1 + ask_depth_1)
- `ask_pressure`: ask_depth_1 / (bid_depth_1 + ask_depth_1)
- `depth_ratio_level_2`: bid_depth_2 / ask_depth_2
- `depth_ratio_level_5`: bid_depth_5 / ask_depth_5
- `microprice`: (bid_1 × ask_depth_1 + ask_1 × bid_depth_1) / (bid_depth_1 + ask_depth_1)
- `order_flow_imbalance`: Recent buy volume - sell volume
- `cancellation_rate`: Order cancellations / orders placed
- `market_impact`: Price change per unit volume
- `resilience`: Speed of order book recovery after large trade
- `toxicity`: Adverse selection indicator

**Liquidity Metrics (5):**
- `bid_ask_slope`: Slope of depth curve
- `order_book_skew`: Skewness of depth distribution
- `effective_liquidity`: Depth within 0.1% of mid price
- `kyle_lambda`: Kyle's Lambda (price impact coefficient)
- `amihud_illiquidity`: |returns| / dollar_volume

#### Category 4: Market Microstructure (18 features)

**Trade Flow (8):**
- `trade_count_1m`: Trades in last 1 minute
- `trade_intensity`: Trades / time
- `trade_size_avg`: Average trade size
- `trade_size_std`: Trade size standard deviation
- `buy_initiated_ratio`: Buyer-initiated trades / total trades
- `sell_initiated_ratio`: Seller-initiated trades / total trades
- `tick_direction`: +1 (uptick), -1 (downtick), 0 (no change)
- `vpin`: Volume-Synchronized Probability of Informed Trading

**Price Impact (5):**
- `price_impact_per_trade`: Avg price change per trade
- `volatility_per_trade`: Avg volatility per trade
- `realized_volatility_5m`: 5-minute realized volatility
- `bid_ask_bounce`: Price oscillation between bid and ask
- `effective_tick_size`: Effective price increment

**Information Flow (5):**
- `quote_update_rate`: Order book updates per second
- `trade_to_quote_ratio`: Trades / quotes
- `order_arrival_rate`: New orders / second
- `informed_trading_prob`: Probability of informed trader presence
- `price_discovery`: Contribution to price formation

#### Category 5: On-Chain Metrics (20 features - Future Implementation)

**Network Activity (8):**
- `active_addresses`: Daily active addresses
- `transaction_count`: Daily transaction count
- `transaction_volume_usd`: Daily transaction volume in USD
- `avg_transaction_value`: Average transaction size
- `hash_rate`: Network hash rate (PoW chains)
- `difficulty`: Mining difficulty
- `block_time`: Average block time
- `gas_price`: Average gas price (Ethereum)

**Exchange Flow (6):**
- `exchange_inflow`: BTC flowing into exchanges
- `exchange_outflow`: BTC flowing out of exchanges
- `exchange_net_flow`: Inflow - outflow
- `exchange_balance`: Total exchange balances
- `whale_transaction_count`: Transactions >$1M
- `large_holder_concentration`: % held by top 100 addresses

**Derivatives & Funding (6):**
- `funding_rate`: Perpetual swap funding rate
- `open_interest`: Total open futures positions
- `long_short_ratio`: Longs / shorts
- `liquidation_volume`: 24h liquidation volume
- `basis`: Futures premium over spot
- `options_put_call_ratio`: Put volume / call volume

---

## Model Architectures

### 2.1 LSTM (Long Short-Term Memory)

**Purpose:** Capture long-term temporal dependencies in price sequences.

**Architecture:**

```python
class LSTMModel(nn.Module):
    def __init__(self, input_size=128, hidden_size=256, num_layers=3, dropout=0.3):
        super().__init__()

        # LSTM layers
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout,
            batch_first=True,
            bidirectional=True  # Bidirectional for better context
        )

        # Attention mechanism
        self.attention = nn.MultiheadAttention(
            embed_dim=hidden_size * 2,  # *2 for bidirectional
            num_heads=8,
            dropout=0.1
        )

        # Fully connected layers
        self.fc1 = nn.Linear(hidden_size * 2, 128)
        self.bn1 = nn.BatchNorm1d(128)
        self.dropout1 = nn.Dropout(0.3)

        self.fc2 = nn.Linear(128, 64)
        self.bn2 = nn.BatchNorm1d(64)
        self.dropout2 = nn.Dropout(0.2)

        # Output layer (3 classes: SHORT, NEUTRAL, LONG)
        self.fc_out = nn.Linear(64, 3)

    def forward(self, x):
        # x shape: (batch, seq_len, features)

        # LSTM forward
        lstm_out, (h_n, c_n) = self.lstm(x)
        # lstm_out shape: (batch, seq_len, hidden_size*2)

        # Apply attention
        attn_out, attn_weights = self.attention(
            lstm_out, lstm_out, lstm_out
        )

        # Take last timestep
        last_out = attn_out[:, -1, :]

        # Fully connected layers
        x = F.relu(self.bn1(self.fc1(last_out)))
        x = self.dropout1(x)

        x = F.relu(self.bn2(self.fc2(x)))
        x = self.dropout2(x)

        # Output logits
        logits = self.fc_out(x)

        return logits, attn_weights
```

**Hyperparameters:**
- Input size: 128 features
- Hidden size: 256 units
- Num layers: 3 LSTM layers
- Dropout: 0.3
- Bidirectional: True
- Attention heads: 8
- Batch size: 256
- Learning rate: 0.001 (Adam optimizer)
- Weight decay: 1e-5

**Training Strategy:**
- Lookback window: 60 timesteps (1 hour of 1-minute data)
- Label: Future 15-minute return (>0.5% = LONG, <-0.5% = SHORT, else NEUTRAL)
- Loss: CrossEntropyLoss with class weights
- Epochs: 50
- Early stopping: Patience 7 epochs on validation loss
- Learning rate schedule: ReduceLROnPlateau (factor=0.5, patience=3)

---

### 2.2 Transformer

**Purpose:** Learn multi-scale attention patterns across features and timeframes.

**Architecture:**

```python
class TransformerModel(nn.Module):
    def __init__(self, input_size=128, d_model=512, nhead=8,
                 num_encoder_layers=6, dim_feedforward=2048, dropout=0.1):
        super().__init__()

        # Input embedding
        self.input_projection = nn.Linear(input_size, d_model)
        self.pos_encoder = PositionalEncoding(d_model, dropout)

        # Transformer encoder
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            activation='gelu',
            batch_first=True
        )

        self.transformer_encoder = nn.TransformerEncoder(
            encoder_layer,
            num_layers=num_encoder_layers,
            norm=nn.LayerNorm(d_model)
        )

        # Multi-scale pooling
        self.avg_pool = nn.AdaptiveAvgPool1d(1)
        self.max_pool = nn.AdaptiveMaxPool1d(1)

        # Fully connected head
        self.fc1 = nn.Linear(d_model * 2, 256)  # *2 for avg+max pooling
        self.bn1 = nn.BatchNorm1d(256)
        self.dropout1 = nn.Dropout(0.3)

        self.fc2 = nn.Linear(256, 128)
        self.bn2 = nn.BatchNorm1d(128)
        self.dropout2 = nn.Dropout(0.2)

        self.fc_out = nn.Linear(128, 3)

    def forward(self, x):
        # x shape: (batch, seq_len, features)

        # Project to d_model dimension
        x = self.input_projection(x)
        x = self.pos_encoder(x)

        # Transformer encoding
        encoded = self.transformer_encoder(x)
        # encoded shape: (batch, seq_len, d_model)

        # Multi-scale pooling
        encoded_t = encoded.transpose(1, 2)  # (batch, d_model, seq_len)
        avg_pooled = self.avg_pool(encoded_t).squeeze(-1)
        max_pooled = self.max_pool(encoded_t).squeeze(-1)
        pooled = torch.cat([avg_pooled, max_pooled], dim=1)

        # Fully connected layers
        x = F.relu(self.bn1(self.fc1(pooled)))
        x = self.dropout1(x)

        x = F.relu(self.bn2(self.fc2(x)))
        x = self.dropout2(x)

        logits = self.fc_out(x)

        return logits


class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() *
                             (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + self.pe[:, :x.size(1), :]
        return self.dropout(x)
```

**Hyperparameters:**
- Input size: 128 features
- d_model: 512 (embedding dimension)
- nhead: 8 attention heads
- num_encoder_layers: 6
- dim_feedforward: 2048
- Dropout: 0.1
- Batch size: 128
- Learning rate: 0.0001 (AdamW optimizer)
- Weight decay: 1e-4
- Warmup steps: 1000

**Training Strategy:**
- Lookback window: 60 timesteps
- Label: Same as LSTM (15-minute future return)
- Loss: Label smoothing CrossEntropyLoss (smoothing=0.1)
- Epochs: 100
- Early stopping: Patience 10 epochs
- Learning rate schedule: Warmup + Cosine annealing

---

### 2.3 CNN (Convolutional Neural Network)

**Purpose:** Extract local patterns and technical indicator signatures.

**Architecture:**

```python
class CNNModel(nn.Module):
    def __init__(self, input_size=128, seq_len=60):
        super().__init__()

        # Multi-scale 1D convolutions
        self.conv1 = nn.Conv1d(input_size, 128, kernel_size=3, padding=1)
        self.bn1 = nn.BatchNorm1d(128)

        self.conv2 = nn.Conv1d(128, 256, kernel_size=5, padding=2)
        self.bn2 = nn.BatchNorm1d(256)

        self.conv3 = nn.Conv1d(256, 256, kernel_size=7, padding=3)
        self.bn3 = nn.BatchNorm1d(256)

        # Inception-like multi-scale conv
        self.inception1 = InceptionModule(256, [64, 64, 64, 64])
        self.inception2 = InceptionModule(256, [64, 64, 64, 64])

        # Global pooling
        self.global_avg_pool = nn.AdaptiveAvgPool1d(1)
        self.global_max_pool = nn.AdaptiveMaxPool1d(1)

        # Fully connected head
        self.fc1 = nn.Linear(512, 256)  # 256*2 from pooling
        self.bn_fc1 = nn.BatchNorm1d(256)
        self.dropout1 = nn.Dropout(0.3)

        self.fc2 = nn.Linear(256, 128)
        self.bn_fc2 = nn.BatchNorm1d(128)
        self.dropout2 = nn.Dropout(0.2)

        self.fc_out = nn.Linear(128, 3)

    def forward(self, x):
        # x shape: (batch, seq_len, features)
        # Transpose for Conv1d: (batch, features, seq_len)
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

        # Fully connected layers
        x = F.relu(self.bn_fc1(self.fc1(pooled)))
        x = self.dropout1(x)

        x = F.relu(self.bn_fc2(self.fc2(x)))
        x = self.dropout2(x)

        logits = self.fc_out(x)

        return logits


class InceptionModule(nn.Module):
    def __init__(self, in_channels, out_channels_list):
        super().__init__()

        # 1x1 conv
        self.conv1x1 = nn.Conv1d(in_channels, out_channels_list[0],
                                 kernel_size=1)

        # 3x3 conv
        self.conv3x3 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_list[1], kernel_size=1),
            nn.BatchNorm1d(out_channels_list[1]),
            nn.ReLU(),
            nn.Conv1d(out_channels_list[1], out_channels_list[1],
                     kernel_size=3, padding=1)
        )

        # 5x5 conv
        self.conv5x5 = nn.Sequential(
            nn.Conv1d(in_channels, out_channels_list[2], kernel_size=1),
            nn.BatchNorm1d(out_channels_list[2]),
            nn.ReLU(),
            nn.Conv1d(out_channels_list[2], out_channels_list[2],
                     kernel_size=5, padding=2)
        )

        # Max pooling path
        self.pool_path = nn.Sequential(
            nn.MaxPool1d(kernel_size=3, stride=1, padding=1),
            nn.Conv1d(in_channels, out_channels_list[3], kernel_size=1)
        )

        self.bn = nn.BatchNorm1d(sum(out_channels_list))

    def forward(self, x):
        out1 = self.conv1x1(x)
        out2 = self.conv3x3(x)
        out3 = self.conv5x5(x)
        out4 = self.pool_path(x)

        out = torch.cat([out1, out2, out3, out4], dim=1)
        out = self.bn(out)
        return F.relu(out)
```

**Hyperparameters:**
- Input size: 128 features
- Conv channels: [128, 256, 256]
- Kernel sizes: [3, 5, 7]
- Inception outputs: [64, 64, 64, 64]
- Batch size: 256
- Learning rate: 0.001 (Adam optimizer)
- Weight decay: 1e-5

**Training Strategy:**
- Lookback window: 60 timesteps
- Label: Same as LSTM
- Loss: Focal Loss (focuses on hard examples)
- Epochs: 50
- Early stopping: Patience 7 epochs
- Data augmentation: Time warping, magnitude warping, window slicing

---

## Ensemble Weighting & Regime Detection

### 3.1 Market Regime Detection

**Purpose:** Classify market state to adaptively weight ensemble models.

**Regimes Defined:**

1. **TRENDING_UP**: ADX > 25, price > SMA(50), MACD > 0
2. **TRENDING_DOWN**: ADX > 25, price < SMA(50), MACD < 0
3. **RANGING**: ADX < 20, Bollinger Band width < 30th percentile
4. **VOLATILE**: ATR > 80th percentile, high price swings

**Regime Detector:**

```python
class RegimeDetector:
    def __init__(self):
        self.lookback = 200  # 200 candles for regime calculation

    def detect_regime(self, df: pd.DataFrame) -> str:
        """
        Detect current market regime.

        Args:
            df: DataFrame with OHLCV + indicators

        Returns:
            Regime string: TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
        """
        # Calculate indicators
        adx = df['adx_14'].iloc[-1]
        price = df['close'].iloc[-1]
        sma_50 = df['sma_50'].iloc[-1]
        macd = df['macd'].iloc[-1]
        bb_width = df['bb_width'].iloc[-1]
        atr = df['atr_14'].iloc[-1]

        # Historical percentiles
        bb_width_p30 = df['bb_width'].quantile(0.30)
        atr_p80 = df['atr_14'].quantile(0.80)

        # Regime classification
        if atr > atr_p80:
            return "VOLATILE"
        elif adx > 25 and price > sma_50 and macd > 0:
            return "TRENDING_UP"
        elif adx > 25 and price < sma_50 and macd < 0:
            return "TRENDING_DOWN"
        elif adx < 20 and bb_width < bb_width_p30:
            return "RANGING"
        else:
            # Default to RANGING if unclear
            return "RANGING"
```

### 3.2 Regime-Adaptive Ensemble Weighting

**Base Weights (Default):**
- LSTM: 40%
- Transformer: 35%
- CNN: 25%

**Regime-Specific Weights:**

| Regime | LSTM Weight | Transformer Weight | CNN Weight | Rationale |
|--------|------------|-------------------|-----------|-----------|
| **TRENDING_UP** | 45% | 40% | 15% | LSTM captures momentum, Transformer sees trend structure |
| **TRENDING_DOWN** | 45% | 40% | 15% | Same as TRENDING_UP |
| **RANGING** | 25% | 30% | 45% | CNN detects mean-reversion patterns |
| **VOLATILE** | 30% | 25% | 45% | CNN reacts faster to local patterns |

**Dynamic Weighting Based on Recent Performance:**

```python
class EnsembleWeighter:
    def __init__(self):
        self.performance_window = 100  # Last 100 predictions
        self.performance_history = {
            'lstm': deque(maxlen=100),
            'transformer': deque(maxlen=100),
            'cnn': deque(maxlen=100)
        }

    def update_performance(self, model_name: str, correct: bool):
        """Update performance history."""
        self.performance_history[model_name].append(1 if correct else 0)

    def get_dynamic_weights(self, regime: str) -> Dict[str, float]:
        """
        Calculate dynamic weights based on regime and recent performance.

        Args:
            regime: Current market regime

        Returns:
            Dict of model weights (sum to 1.0)
        """
        # Base weights for regime
        base_weights = {
            'TRENDING_UP': {'lstm': 0.45, 'transformer': 0.40, 'cnn': 0.15},
            'TRENDING_DOWN': {'lstm': 0.45, 'transformer': 0.40, 'cnn': 0.15},
            'RANGING': {'lstm': 0.25, 'transformer': 0.30, 'cnn': 0.45},
            'VOLATILE': {'lstm': 0.30, 'transformer': 0.25, 'cnn': 0.45}
        }

        weights = base_weights.get(regime,
                                   {'lstm': 0.40, 'transformer': 0.35, 'cnn': 0.25})

        # Adjust based on recent performance (if enough history)
        if all(len(hist) >= 20 for hist in self.performance_history.values()):
            lstm_acc = np.mean(self.performance_history['lstm'])
            transformer_acc = np.mean(self.performance_history['transformer'])
            cnn_acc = np.mean(self.performance_history['cnn'])

            # Performance-based adjustment (max ±10%)
            total_acc = lstm_acc + transformer_acc + cnn_acc
            if total_acc > 0:
                perf_factor = {
                    'lstm': (lstm_acc / total_acc - 1/3) * 0.3,  # Max ±10%
                    'transformer': (transformer_acc / total_acc - 1/3) * 0.3,
                    'cnn': (cnn_acc / total_acc - 1/3) * 0.3
                }

                weights['lstm'] += perf_factor['lstm']
                weights['transformer'] += perf_factor['transformer']
                weights['cnn'] += perf_factor['cnn']

                # Normalize to sum to 1.0
                total = sum(weights.values())
                weights = {k: v/total for k, v in weights.items()}

        return weights
```

### 3.3 Ensemble Prediction

```python
class MLEnsemble:
    def __init__(self, lstm_model, transformer_model, cnn_model):
        self.lstm = lstm_model
        self.transformer = transformer_model
        self.cnn = cnn_model
        self.regime_detector = RegimeDetector()
        self.weighter = EnsembleWeighter()

    def predict(self, features: np.ndarray,
                regime_df: pd.DataFrame) -> Dict[str, Any]:
        """
        Ensemble prediction with regime-adaptive weighting.

        Args:
            features: Input features (60, 128)
            regime_df: DataFrame for regime detection

        Returns:
            Dict with prediction, probabilities, confidence
        """
        # Detect regime
        regime = self.regime_detector.detect_regime(regime_df)

        # Get dynamic weights
        weights = self.weighter.get_dynamic_weights(regime)

        # Individual model predictions (logits)
        with torch.no_grad():
            lstm_logits, _ = self.lstm(features)
            transformer_logits = self.transformer(features)
            cnn_logits = self.cnn(features)

        # Convert to probabilities
        lstm_probs = F.softmax(lstm_logits, dim=-1).cpu().numpy()
        transformer_probs = F.softmax(transformer_logits, dim=-1).cpu().numpy()
        cnn_probs = F.softmax(cnn_logits, dim=-1).cpu().numpy()

        # Weighted ensemble
        ensemble_probs = (
            weights['lstm'] * lstm_probs +
            weights['transformer'] * transformer_probs +
            weights['cnn'] * cnn_probs
        )

        # Prediction and confidence
        prediction = np.argmax(ensemble_probs)
        confidence = ensemble_probs[prediction]

        return {
            'prediction': prediction,  # 0=SHORT, 1=NEUTRAL, 2=LONG
            'probabilities': ensemble_probs.tolist(),
            'confidence': float(confidence),
            'regime': regime,
            'weights': weights,
            'individual_predictions': {
                'lstm': lstm_probs.tolist(),
                'transformer': transformer_probs.tolist(),
                'cnn': cnn_probs.tolist()
            }
        }
```

---

## Confidence Score Calibration

### 4.1 Problem: Uncalibrated Probabilities

Deep neural networks often produce **overconfident** predictions. A 90% predicted probability may only be correct 70% of the time in practice.

**Solution:** Use **Platt scaling** (temperature scaling) on validation set to calibrate probabilities.

### 4.2 Platt Scaling Implementation

```python
from sklearn.linear_model import LogisticRegression

class ConfidenceCalibrator:
    def __init__(self):
        self.calibrator = None

    def fit(self, logits: np.ndarray, labels: np.ndarray):
        """
        Fit Platt scaling on validation set.

        Args:
            logits: Model outputs before softmax (n_samples, n_classes)
            labels: True labels (n_samples,)
        """
        # Use logistic regression to learn calibration
        self.calibrator = LogisticRegression()

        # Flatten for binary calibration (each class vs rest)
        self.calibrator.fit(logits, labels)

    def calibrate(self, logits: np.ndarray) -> np.ndarray:
        """
        Calibrate logits to probabilities.

        Args:
            logits: Model outputs (n_samples, n_classes)

        Returns:
            Calibrated probabilities (n_samples, n_classes)
        """
        if self.calibrator is None:
            raise ValueError("Calibrator not fitted. Call fit() first.")

        return self.calibrator.predict_proba(logits)
```

### 4.3 Temperature Scaling (Alternative)

```python
class TemperatureScaler:
    def __init__(self):
        self.temperature = None

    def fit(self, logits: np.ndarray, labels: np.ndarray):
        """
        Find optimal temperature via NLL minimization on validation set.

        Args:
            logits: Model outputs (n_samples, n_classes)
            labels: True labels (n_samples,)
        """
        from scipy.optimize import minimize

        def nll_loss(temperature):
            scaled_logits = logits / temperature
            probs = scipy.special.softmax(scaled_logits, axis=1)
            nll = -np.mean(np.log(probs[range(len(labels)), labels] + 1e-8))
            return nll

        result = minimize(nll_loss, x0=[1.0], bounds=[(0.1, 10.0)])
        self.temperature = result.x[0]

        print(f"Optimal temperature: {self.temperature:.3f}")

    def calibrate(self, logits: np.ndarray) -> np.ndarray:
        """Apply temperature scaling."""
        if self.temperature is None:
            raise ValueError("Temperature not fitted.")

        scaled_logits = logits / self.temperature
        return scipy.special.softmax(scaled_logits, axis=1)
```

### 4.4 Risk Parameter Calibration

**Goal:** Convert confidence scores to position sizing multipliers.

**Calibration Curve:**
- Confidence < 0.6: Reject signal (too uncertain)
- Confidence 0.6-0.7: Size × 0.5 (low confidence)
- Confidence 0.7-0.8: Size × 1.0 (medium confidence)
- Confidence 0.8-0.9: Size × 1.5 (high confidence)
- Confidence 0.9-1.0: Size × 2.0 (very high confidence, capped at $2000 max)

```python
def confidence_to_size_multiplier(confidence: float) -> float:
    """Convert calibrated confidence to position size multiplier."""
    if confidence < 0.6:
        return 0.0  # Reject
    elif confidence < 0.7:
        return 0.5
    elif confidence < 0.8:
        return 1.0
    elif confidence < 0.9:
        return 1.5
    else:
        return 2.0
```

---

## Training Pipeline

### 5.1 Data Preparation

**Historical Data Collection:**

```python
import ccxt
from datetime import datetime, timedelta

class DataCollector:
    def __init__(self, exchange='kraken'):
        self.exchange = getattr(ccxt, exchange)()

    def fetch_ohlcv(self, symbol: str, timeframe: str = '1m',
                    since: datetime = None, limit: int = 1000):
        """
        Fetch historical OHLCV data.

        Args:
            symbol: Trading pair (e.g., 'BTC/USD')
            timeframe: Candle timeframe (1m, 5m, 15m, 1h, 1d)
            since: Start date
            limit: Number of candles

        Returns:
            DataFrame with OHLCV data
        """
        if since is None:
            since = datetime.now() - timedelta(days=365*5)  # 5 years

        since_ms = int(since.timestamp() * 1000)

        all_ohlcv = []
        while True:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol, timeframe, since=since_ms, limit=limit
            )

            if not ohlcv:
                break

            all_ohlcv.extend(ohlcv)

            # Update since for next batch
            since_ms = ohlcv[-1][0] + 1

            # Sleep to avoid rate limits
            time.sleep(self.exchange.rateLimit / 1000)

            # Break if less than limit returned (end of data)
            if len(ohlcv) < limit:
                break

        df = pd.DataFrame(
            all_ohlcv,
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)

        return df
```

### 5.2 Feature Engineering

```python
class FeatureEngineer:
    def __init__(self):
        pass

    def engineer_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Apply feature engineering to OHLCV data.

        Args:
            df: DataFrame with OHLCV columns

        Returns:
            DataFrame with 128 engineered features
        """
        df = df.copy()

        # Price action features
        df = self._add_price_features(df)
        df = self._add_momentum_features(df)
        df = self._add_trend_features(df)
        df = self._add_volatility_features(df)
        df = self._add_oscillators(df)

        # Volume features
        df = self._add_volume_features(df)
        df = self._add_volume_price_features(df)

        # Order book features (if available)
        # df = self._add_orderbook_features(df)

        # Drop NaN rows created by indicators
        df = df.dropna()

        return df

    def _add_price_features(self, df):
        # Returns
        df['returns_1m'] = df['close'].pct_change(1)
        df['returns_5m'] = df['close'].pct_change(5)
        df['returns_15m'] = df['close'].pct_change(15)
        df['returns_1h'] = df['close'].pct_change(60)
        df['log_returns_1m'] = np.log(df['close'] / df['close'].shift(1))

        # HL spread
        df['hl_spread'] = (df['high'] - df['low']) / df['close']

        return df

    def _add_momentum_features(self, df):
        df['momentum_14'] = df['close'].diff(14)
        df['roc_9'] = ((df['close'] - df['close'].shift(9)) /
                       df['close'].shift(9) * 100)
        return df

    def _add_trend_features(self, df):
        # SMAs
        df['sma_20'] = df['close'].rolling(20).mean()
        df['sma_50'] = df['close'].rolling(50).mean()
        df['sma_200'] = df['close'].rolling(200).mean()

        # EMAs
        df['ema_12'] = df['close'].ewm(span=12).mean()
        df['ema_26'] = df['close'].ewm(span=26).mean()

        # MACD
        df['macd'] = df['ema_12'] - df['ema_26']
        df['macd_signal'] = df['macd'].ewm(span=9).mean()
        df['macd_histogram'] = df['macd'] - df['macd_signal']

        # Price/SMA ratios
        df['price_sma_ratio_20'] = df['close'] / df['sma_20']
        df['price_sma_ratio_50'] = df['close'] / df['sma_50']

        # ADX (simplified)
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()
        df['adx_14'] = atr  # Simplified, use talib for accurate ADX

        return df

    def _add_volatility_features(self, df):
        # ATR
        high_low = df['high'] - df['low']
        high_close = np.abs(df['high'] - df['close'].shift())
        low_close = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        df['atr_14'] = tr.rolling(14).mean()

        # Bollinger Bands
        df['bb_middle'] = df['close'].rolling(20).mean()
        bb_std = df['close'].rolling(20).std()
        df['bb_upper'] = df['bb_middle'] + 2 * bb_std
        df['bb_lower'] = df['bb_middle'] - 2 * bb_std
        df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
        df['bb_position'] = ((df['close'] - df['bb_lower']) /
                             (df['bb_upper'] - df['bb_lower']))

        return df

    def _add_oscillators(self, df):
        # RSI
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        df['rsi_14'] = 100 - (100 / (1 + rs))
        df['rsi_21'] = 100 - (100 / (1 + rs.rolling(21).mean()))

        # Stochastic
        low_14 = df['low'].rolling(14).min()
        high_14 = df['high'].rolling(14).max()
        df['stoch_k'] = 100 * (df['close'] - low_14) / (high_14 - low_14)
        df['stoch_d'] = df['stoch_k'].rolling(3).mean()

        return df

    def _add_volume_features(self, df):
        df['volume_sma_20'] = df['volume'].rolling(20).mean()
        df['volume_ratio'] = df['volume'] / df['volume_sma_20']

        # OBV
        df['obv'] = (np.sign(df['close'].diff()) * df['volume']).fillna(0).cumsum()
        df['obv_ema_20'] = df['obv'].ewm(span=20).mean()

        # VWAP
        df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

        return df

    def _add_volume_price_features(self, df):
        # Buying/selling pressure
        df['buying_pressure'] = ((df['close'] - df['low']) /
                                 (df['high'] - df['low'] + 1e-8) * df['volume'])
        df['selling_pressure'] = ((df['high'] - df['close']) /
                                  (df['high'] - df['low'] + 1e-8) * df['volume'])
        df['buy_sell_ratio'] = (df['buying_pressure'] /
                                (df['selling_pressure'] + 1e-8))

        return df
```

### 5.3 Labeling Strategy

```python
class LabelGenerator:
    def __init__(self, forward_window=15, threshold=0.005):
        """
        Args:
            forward_window: Minutes to look ahead (default 15)
            threshold: Return threshold for LONG/SHORT (default 0.5%)
        """
        self.forward_window = forward_window
        self.threshold = threshold

    def generate_labels(self, df: pd.DataFrame) -> pd.Series:
        """
        Generate labels based on future returns.

        Returns:
            Series with labels: 0=SHORT, 1=NEUTRAL, 2=LONG
        """
        # Calculate forward returns
        forward_returns = df['close'].pct_change(self.forward_window).shift(-self.forward_window)

        # Classify
        labels = pd.Series(1, index=df.index)  # Default NEUTRAL
        labels[forward_returns > self.threshold] = 2  # LONG
        labels[forward_returns < -self.threshold] = 0  # SHORT

        return labels
```

### 5.4 Training Loop

```python
class ModelTrainer:
    def __init__(self, model, device='cuda'):
        self.model = model.to(device)
        self.device = device

    def train_epoch(self, train_loader, optimizer, criterion):
        """Train for one epoch."""
        self.model.train()
        total_loss = 0
        correct = 0
        total = 0

        for batch_idx, (X, y) in enumerate(train_loader):
            X, y = X.to(self.device), y.to(self.device)

            optimizer.zero_grad()

            # Forward pass
            if isinstance(self.model, LSTMModel):
                outputs, _ = self.model(X)
            else:
                outputs = self.model(X)

            loss = criterion(outputs, y)

            # Backward pass
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), max_norm=1.0)
            optimizer.step()

            # Metrics
            total_loss += loss.item()
            _, predicted = outputs.max(1)
            total += y.size(0)
            correct += predicted.eq(y).sum().item()

        avg_loss = total_loss / len(train_loader)
        accuracy = 100. * correct / total

        return avg_loss, accuracy

    def validate(self, val_loader, criterion):
        """Validate on validation set."""
        self.model.eval()
        total_loss = 0
        correct = 0
        total = 0

        with torch.no_grad():
            for X, y in val_loader:
                X, y = X.to(self.device), y.to(self.device)

                if isinstance(self.model, LSTMModel):
                    outputs, _ = self.model(X)
                else:
                    outputs = self.model(X)

                loss = criterion(outputs, y)

                total_loss += loss.item()
                _, predicted = outputs.max(1)
                total += y.size(0)
                correct += predicted.eq(y).sum().item()

        avg_loss = total_loss / len(val_loader)
        accuracy = 100. * correct / total

        return avg_loss, accuracy

    def train(self, train_loader, val_loader, epochs=50, lr=0.001):
        """Full training loop with early stopping."""
        optimizer = torch.optim.Adam(self.model.parameters(), lr=lr,
                                     weight_decay=1e-5)
        criterion = nn.CrossEntropyLoss()
        scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            optimizer, mode='min', factor=0.5, patience=3, verbose=True
        )

        best_val_loss = float('inf')
        patience_counter = 0
        patience = 7

        for epoch in range(epochs):
            train_loss, train_acc = self.train_epoch(train_loader, optimizer, criterion)
            val_loss, val_acc = self.validate(val_loader, criterion)

            scheduler.step(val_loss)

            print(f"Epoch {epoch+1}/{epochs}")
            print(f"Train Loss: {train_loss:.4f}, Train Acc: {train_acc:.2f}%")
            print(f"Val Loss: {val_loss:.4f}, Val Acc: {val_acc:.2f}%")

            # Early stopping
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                patience_counter = 0
                # Save best model
                torch.save(self.model.state_dict(), 'best_model.pth')
            else:
                patience_counter += 1

            if patience_counter >= patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

        # Load best model
        self.model.load_state_dict(torch.load('best_model.pth'))
```

---

## Evaluation & Cross-Validation

### 6.1 Time-Series Cross-Validation

**Problem:** Standard k-fold CV doesn't respect temporal ordering.

**Solution:** Use **TimeSeriesSplit** or **walk-forward validation**.

```python
from sklearn.model_selection import TimeSeriesSplit

class TimeSeriesValidator:
    def __init__(self, n_splits=5):
        self.n_splits = n_splits
        self.tscv = TimeSeriesSplit(n_splits=n_splits)

    def cross_validate(self, X, y, model_class, **model_kwargs):
        """
        Perform time-series cross-validation.

        Args:
            X: Features (n_samples, seq_len, n_features)
            y: Labels (n_samples,)
            model_class: Model class to instantiate
            model_kwargs: Model hyperparameters

        Returns:
            List of validation metrics for each fold
        """
        fold_metrics = []

        for fold, (train_idx, val_idx) in enumerate(self.tscv.split(X)):
            print(f"\nFold {fold + 1}/{self.n_splits}")

            X_train, X_val = X[train_idx], X[val_idx]
            y_train, y_val = y[train_idx], y[val_idx]

            # Create dataloaders
            train_dataset = TensorDataset(
                torch.FloatTensor(X_train),
                torch.LongTensor(y_train)
            )
            val_dataset = TensorDataset(
                torch.FloatTensor(X_val),
                torch.LongTensor(y_val)
            )

            train_loader = DataLoader(train_dataset, batch_size=256, shuffle=True)
            val_loader = DataLoader(val_dataset, batch_size=256, shuffle=False)

            # Train model
            model = model_class(**model_kwargs)
            trainer = ModelTrainer(model)
            trainer.train(train_loader, val_loader, epochs=30)

            # Evaluate on validation fold
            metrics = self.evaluate_model(trainer.model, val_loader)
            fold_metrics.append(metrics)

            print(f"Fold {fold + 1} Metrics:")
            print(f"  Accuracy: {metrics['accuracy']:.2f}%")
            print(f"  Precision: {metrics['precision']:.3f}")
            print(f"  Recall: {metrics['recall']:.3f}")
            print(f"  F1: {metrics['f1']:.3f}")

        # Aggregate metrics
        avg_metrics = {
            key: np.mean([m[key] for m in fold_metrics])
            for key in fold_metrics[0].keys()
        }

        return fold_metrics, avg_metrics

    def evaluate_model(self, model, val_loader):
        """Evaluate model and return metrics."""
        model.eval()
        all_preds = []
        all_labels = []

        with torch.no_grad():
            for X, y in val_loader:
                X = X.cuda()
                if isinstance(model, LSTMModel):
                    outputs, _ = model(X)
                else:
                    outputs = model(X)

                _, preds = outputs.max(1)
                all_preds.extend(preds.cpu().numpy())
                all_labels.extend(y.numpy())

        from sklearn.metrics import accuracy_score, precision_recall_fscore_support

        accuracy = accuracy_score(all_labels, all_preds) * 100
        precision, recall, f1, _ = precision_recall_fscore_support(
            all_labels, all_preds, average='macro', zero_division=0
        )

        return {
            'accuracy': accuracy,
            'precision': precision,
            'recall': recall,
            'f1': f1
        }
```

### 6.2 Trading Performance Metrics

```python
class TradingEvaluator:
    def __init__(self):
        pass

    def evaluate_trading_performance(self, predictions, labels, prices,
                                     position_size=100):
        """
        Calculate trading metrics.

        Args:
            predictions: Model predictions (0=SHORT, 1=NEUTRAL, 2=LONG)
            labels: True labels
            prices: Price series (for P&L calculation)
            position_size: Base position size in USD

        Returns:
            Dict with trading metrics
        """
        trades = []

        for i in range(len(predictions)):
            if predictions[i] == 1:  # NEUTRAL, no trade
                continue

            # Entry
            entry_price = prices[i]
            side = 'LONG' if predictions[i] == 2 else 'SHORT'

            # Exit after 15 minutes (forward window)
            exit_idx = min(i + 15, len(prices) - 1)
            exit_price = prices[exit_idx]

            # P&L
            if side == 'LONG':
                pnl = (exit_price - entry_price) / entry_price * position_size
            else:
                pnl = (entry_price - exit_price) / entry_price * position_size

            # Fees (Kraken: 0.26% taker fee × 2)
            fees = position_size * 0.0026 * 2
            net_pnl = pnl - fees

            trades.append({
                'entry_price': entry_price,
                'exit_price': exit_price,
                'side': side,
                'pnl': net_pnl,
                'return_pct': net_pnl / position_size * 100
            })

        if not trades:
            return {'error': 'No trades generated'}

        # Calculate metrics
        returns = [t['return_pct'] for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        win_rate = len(wins) / len(returns) * 100 if returns else 0
        avg_win = np.mean(wins) if wins else 0
        avg_loss = np.mean(losses) if losses else 0
        profit_factor = abs(sum(wins) / sum(losses)) if losses else float('inf')

        # Sharpe ratio (annualized)
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        sharpe = (mean_return / std_return) * np.sqrt(252 * 24 * 4) if std_return > 0 else 0

        # Max drawdown
        cumulative = np.cumsum(returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = cumulative - running_max
        max_drawdown = np.min(drawdown)

        return {
            'total_trades': len(trades),
            'win_rate': win_rate,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
            'total_return': sum(returns),
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'trades': trades
        }
```

---

## Signal Publishing to Redis

### 7.1 Probability-Rich Signal Format

```python
@dataclass
class MLSignal:
    """Probability-rich signal with ML ensemble details."""
    signal_id: str
    timestamp: datetime
    pair: str
    prediction: str  # LONG, SHORT, NEUTRAL
    confidence: float  # Calibrated probability
    probabilities: Dict[str, float]  # {SHORT: 0.1, NEUTRAL: 0.2, LONG: 0.7}
    regime: str  # TRENDING_UP, TRENDING_DOWN, RANGING, VOLATILE
    ensemble_weights: Dict[str, float]  # {lstm: 0.45, transformer: 0.40, cnn: 0.15}
    individual_predictions: Dict[str, List[float]]  # {lstm: [0.2, 0.1, 0.7], ...}
    feature_importance: Dict[str, float]  # Top 10 features
    model_version: str  # e.g., "v2.3.0_2025-11"

    def to_redis_dict(self) -> Dict[str, str]:
        """Convert to Redis-compatible dict (all values as strings)."""
        return {
            'signal_id': self.signal_id,
            'timestamp': self.timestamp.isoformat(),
            'pair': self.pair,
            'prediction': self.prediction,
            'confidence': str(self.confidence),
            'probabilities': json.dumps(self.probabilities),
            'regime': self.regime,
            'ensemble_weights': json.dumps(self.ensemble_weights),
            'individual_predictions': json.dumps(self.individual_predictions),
            'feature_importance': json.dumps(self.feature_importance),
            'model_version': self.model_version
        }
```

### 7.2 Redis Publisher

```python
import redis
import json
from datetime import datetime

class MLSignalPublisher:
    def __init__(self, redis_url: str, ssl_cert_path: str = None):
        """
        Args:
            redis_url: rediss://default:password@host:port
            ssl_cert_path: Path to CA certificate
        """
        self.redis_client = redis.from_url(
            redis_url,
            decode_responses=True,
            ssl_cert_reqs='required',
            ssl_ca_certs=ssl_cert_path
        )

    def publish_signal(self, ml_signal: MLSignal, stream_name: str = 'ml:signals'):
        """
        Publish ML signal to Redis stream.

        Args:
            ml_signal: MLSignal object
            stream_name: Redis stream name (default: ml:signals)
        """
        signal_dict = ml_signal.to_redis_dict()

        try:
            # Publish to stream with MAXLEN trimming
            message_id = self.redis_client.xadd(
                stream_name,
                signal_dict,
                id=ml_signal.signal_id,  # Use signal_id for idempotency
                maxlen=10000,
                approximate=True
            )

            print(f"Published signal {ml_signal.signal_id} to {stream_name}")
            return message_id

        except redis.exceptions.RedisError as e:
            print(f"Error publishing signal: {e}")
            # Retry logic could be added here
            raise

    def publish_batch(self, ml_signals: List[MLSignal], stream_name: str = 'ml:signals'):
        """Publish multiple signals using pipeline for efficiency."""
        pipe = self.redis_client.pipeline()

        for signal in ml_signals:
            signal_dict = signal.to_redis_dict()
            pipe.xadd(stream_name, signal_dict, maxlen=10000, approximate=True)

        pipe.execute()
        print(f"Published {len(ml_signals)} signals to {stream_name}")
```

---

## Monthly Retraining Pipeline

### 8.1 Retraining Script

```python
#!/usr/bin/env python3
"""
Monthly ML model retraining script.

Usage:
    python scripts/retrain_models.py --config config/training_config.yaml
"""

import argparse
import yaml
from datetime import datetime, timedelta
import boto3
import torch

class MonthlyRetrainer:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.s3_client = boto3.client('s3')
        self.bucket_name = self.config['s3']['bucket']

    def collect_training_data(self):
        """Fetch last 5 years of data from Kraken."""
        print("Collecting training data...")
        collector = DataCollector(exchange='kraken')

        pairs = self.config['trading_pairs']
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365*5)

        all_data = {}
        for pair in pairs:
            print(f"Fetching {pair}...")
            df = collector.fetch_ohlcv(pair, timeframe='1m', since=start_date)
            all_data[pair] = df

        # Save raw data
        for pair, df in all_data.items():
            df.to_parquet(f'data/raw/{pair.replace("/", "_")}_raw.parquet')

        return all_data

    def engineer_features(self, data_dict):
        """Apply feature engineering to all pairs."""
        print("Engineering features...")
        engineer = FeatureEngineer()

        engineered_data = {}
        for pair, df in data_dict.items():
            print(f"Engineering {pair}...")
            df_feat = engineer.engineer_features(df)
            engineered_data[pair] = df_feat

            # Save engineered data
            df_feat.to_parquet(f'data/engineered/{pair.replace("/", "_")}_features.parquet')

        return engineered_data

    def prepare_datasets(self, data_dict):
        """Create train/val/test splits."""
        print("Preparing datasets...")
        label_gen = LabelGenerator(forward_window=15, threshold=0.005)

        all_X = []
        all_y = []

        for pair, df in data_dict.items():
            # Generate labels
            labels = label_gen.generate_labels(df)

            # Create sequences
            feature_cols = [col for col in df.columns if col not in ['timestamp']]
            X = self._create_sequences(df[feature_cols].values, window=60)
            y = labels.values[60:]  # Align with sequences

            all_X.append(X)
            all_y.append(y)

        # Concatenate all pairs
        X = np.concatenate(all_X, axis=0)
        y = np.concatenate(all_y, axis=0)

        # Time-series split: 70% train, 15% val, 15% test
        n = len(X)
        train_end = int(n * 0.70)
        val_end = int(n * 0.85)

        X_train, y_train = X[:train_end], y[:train_end]
        X_val, y_val = X[train_end:val_end], y[train_end:val_end]
        X_test, y_test = X[val_end:], y[val_end:]

        print(f"Train: {len(X_train)}, Val: {len(X_val)}, Test: {len(X_test)}")

        return (X_train, y_train), (X_val, y_val), (X_test, y_test)

    def _create_sequences(self, data, window=60):
        """Create sliding window sequences."""
        sequences = []
        for i in range(len(data) - window):
            sequences.append(data[i:i+window])
        return np.array(sequences)

    def train_models(self, train_data, val_data):
        """Train LSTM, Transformer, CNN."""
        print("Training models...")
        X_train, y_train = train_data
        X_val, y_val = val_data

        models = {}

        # Train LSTM
        print("\n=== Training LSTM ===")
        lstm = LSTMModel(input_size=128, hidden_size=256, num_layers=3)
        lstm_trainer = ModelTrainer(lstm)
        lstm_trainer.train(
            self._create_dataloader(X_train, y_train, batch_size=256),
            self._create_dataloader(X_val, y_val, batch_size=256),
            epochs=50, lr=0.001
        )
        models['lstm'] = lstm

        # Train Transformer
        print("\n=== Training Transformer ===")
        transformer = TransformerModel(input_size=128, d_model=512, nhead=8)
        transformer_trainer = ModelTrainer(transformer)
        transformer_trainer.train(
            self._create_dataloader(X_train, y_train, batch_size=128),
            self._create_dataloader(X_val, y_val, batch_size=128),
            epochs=100, lr=0.0001
        )
        models['transformer'] = transformer

        # Train CNN
        print("\n=== Training CNN ===")
        cnn = CNNModel(input_size=128, seq_len=60)
        cnn_trainer = ModelTrainer(cnn)
        cnn_trainer.train(
            self._create_dataloader(X_train, y_train, batch_size=256),
            self._create_dataloader(X_val, y_val, batch_size=256),
            epochs=50, lr=0.001
        )
        models['cnn'] = cnn

        return models

    def _create_dataloader(self, X, y, batch_size):
        """Helper to create DataLoader."""
        dataset = TensorDataset(torch.FloatTensor(X), torch.LongTensor(y))
        return DataLoader(dataset, batch_size=batch_size, shuffle=True)

    def evaluate_models(self, models, test_data):
        """Evaluate on test set."""
        print("\n=== Evaluating Models ===")
        X_test, y_test = test_data
        test_loader = self._create_dataloader(X_test, y_test, batch_size=256)

        evaluator = TradingEvaluator()
        results = {}

        for name, model in models.items():
            print(f"\nEvaluating {name}...")
            # Classification metrics
            trainer = ModelTrainer(model)
            metrics = TimeSeriesValidator().evaluate_model(model, test_loader)

            # Trading metrics (simplified, assumes price data available)
            # In practice, you'd align predictions with actual price data

            results[name] = metrics
            print(f"{name} - Accuracy: {metrics['accuracy']:.2f}%, "
                  f"F1: {metrics['f1']:.3f}")

        return results

    def save_models(self, models, version: str):
        """Save models to S3 and local storage."""
        print(f"\nSaving models (version {version})...")

        for name, model in models.items():
            # Local save
            model_path = f'models/{name}_{version}.pth'
            torch.save(model.state_dict(), model_path)
            print(f"Saved {name} to {model_path}")

            # S3 upload
            s3_key = f'models/{name}/{name}_{version}.pth'
            self.s3_client.upload_file(model_path, self.bucket_name, s3_key)
            print(f"Uploaded to s3://{self.bucket_name}/{s3_key}")

        # Save metadata
        metadata = {
            'version': version,
            'timestamp': datetime.now().isoformat(),
            'models': list(models.keys()),
            'training_data_size': 'N/A',  # Add actual size
            'hyperparameters': self.config.get('hyperparameters', {})
        }

        metadata_path = f'models/metadata_{version}.json'
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)

        # Upload metadata to S3
        self.s3_client.upload_file(
            metadata_path,
            self.bucket_name,
            f'models/metadata/{version}.json'
        )

    def run_retraining(self):
        """Full retraining pipeline."""
        version = datetime.now().strftime("v%Y%m")  # e.g., v202511

        print(f"Starting monthly retraining - Version: {version}")
        print("="*60)

        # Step 1: Collect data
        raw_data = self.collect_training_data()

        # Step 2: Feature engineering
        engineered_data = self.engineer_features(raw_data)

        # Step 3: Prepare datasets
        train_data, val_data, test_data = self.prepare_datasets(engineered_data)

        # Step 4: Train models
        models = self.train_models(train_data, val_data)

        # Step 5: Evaluate
        results = self.evaluate_models(models, test_data)

        # Step 6: Decision - deploy if improved
        # Compare with previous version (implement logic)
        deploy = True  # Simplified

        if deploy:
            # Step 7: Save models
            self.save_models(models, version)
            print(f"\n✓ Retraining complete - Version {version} deployed")
        else:
            print("\n✗ New models did not improve - keeping previous version")

        return version, results


def main():
    parser = argparse.ArgumentParser(description='Monthly model retraining')
    parser.add_argument('--config', required=True, help='Training config YAML')
    args = parser.parse_args()

    retrainer = MonthlyRetrainer(args.config)
    version, results = retrainer.run_retraining()

    print(f"\nRetraining completed: {version}")
    print("Results:", json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
```

### 8.2 GitHub Actions Workflow

```yaml
# .github/workflows/monthly_retrain.yml
name: Monthly ML Model Retraining

on:
  schedule:
    # Run on 1st of every month at 00:00 UTC
    - cron: '0 0 1 * *'
  workflow_dispatch:  # Manual trigger

jobs:
  retrain:
    runs-on: ubuntu-latest
    timeout-minutes: 720  # 12 hours max

    steps:
      - name: Checkout code
        uses: actions/checkout@v4
        with:
          lfs: true  # Git LFS for large model files

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

      - name: Configure AWS credentials
        uses: aws-actions/configure-aws-credentials@v4
        with:
          aws-access-key-id: ${{ secrets.AWS_ACCESS_KEY_ID }}
          aws-secret-access-key: ${{ secrets.AWS_SECRET_ACCESS_KEY }}
          aws-region: us-east-1

      - name: Run retraining script
        env:
          REDIS_URL: ${{ secrets.REDIS_URL }}
          KRAKEN_API_KEY: ${{ secrets.KRAKEN_API_KEY }}
          KRAKEN_API_SECRET: ${{ secrets.KRAKEN_API_SECRET }}
        run: |
          python scripts/retrain_models.py --config config/training_config.yaml

      - name: Upload models to Git LFS
        if: success()
        run: |
          git config user.name "GitHub Actions Bot"
          git config user.email "actions@github.com"
          git lfs track "models/*.pth"
          git add models/*.pth models/metadata_*.json
          git commit -m "chore: monthly model retrain $(date +%Y-%m)"
          git push

      - name: Notify Slack
        if: always()
        uses: 8398a7/action-slack@v3
        with:
          status: ${{ job.status }}
          text: 'Monthly ML model retraining ${{ job.status }}'
          webhook_url: ${{ secrets.SLACK_WEBHOOK_URL }}
```

---

## Monitoring & Drift Detection

### 9.1 Model Performance Monitoring

```python
class ModelMonitor:
    def __init__(self, redis_client):
        self.redis_client = redis_client
        self.performance_window = 1000  # Last 1000 predictions

    def log_prediction(self, model_name: str, prediction: int,
                      actual: int, confidence: float):
        """Log each prediction for monitoring."""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'model': model_name,
            'prediction': prediction,
            'actual': actual,
            'confidence': confidence,
            'correct': int(prediction == actual)
        }

        # Store in Redis stream
        self.redis_client.xadd(
            'ml:monitoring:predictions',
            log_entry,
            maxlen=10000,
            approximate=True
        )

    def calculate_drift_score(self, feature_distribution_new,
                             feature_distribution_train):
        """
        Calculate distribution drift using KL divergence.

        Returns:
            Drift score (higher = more drift)
        """
        from scipy.stats import entropy

        drift_scores = []
        for i in range(len(feature_distribution_new)):
            p = feature_distribution_train[i] + 1e-10
            q = feature_distribution_new[i] + 1e-10
            kl_div = entropy(p, q)
            drift_scores.append(kl_div)

        avg_drift = np.mean(drift_scores)
        return avg_drift

    def check_performance_degradation(self, model_name: str,
                                     threshold: float = 0.05):
        """
        Check if model performance has degraded significantly.

        Args:
            model_name: Model to check
            threshold: Acceptable degradation (5% default)

        Returns:
            True if degraded, False otherwise
        """
        # Fetch recent predictions
        recent = self.redis_client.xrevrange(
            'ml:monitoring:predictions',
            count=self.performance_window
        )

        model_preds = [
            p for p in recent
            if p[1].get('model') == model_name
        ]

        if len(model_preds) < 100:
            return False  # Not enough data

        # Calculate recent accuracy
        recent_acc = np.mean([
            int(p[1].get('correct', 0))
            for p in model_preds
        ])

        # Compare with training accuracy (stored in metadata)
        training_acc = 0.65  # Retrieve from model metadata

        degradation = training_acc - recent_acc

        if degradation > threshold:
            print(f"⚠️ Model {model_name} degraded by {degradation*100:.1f}%")
            print(f"   Training acc: {training_acc:.2%}")
            print(f"   Recent acc: {recent_acc:.2%}")
            return True

        return False
```

### 9.2 Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge

# ML-specific metrics
ml_predictions_total = Counter(
    'ml_predictions_total',
    'Total ML predictions',
    ['model', 'prediction', 'regime']
)

ml_prediction_confidence = Histogram(
    'ml_prediction_confidence',
    'ML prediction confidence scores',
    ['model'],
    buckets=[0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.0]
)

ml_model_accuracy = Gauge(
    'ml_model_accuracy',
    'Recent model accuracy (last 1000 predictions)',
    ['model', 'regime']
)

ml_ensemble_weight = Gauge(
    'ml_ensemble_weight',
    'Current ensemble weight',
    ['model', 'regime']
)

ml_inference_latency = Histogram(
    'ml_inference_latency_ms',
    'ML inference latency in milliseconds',
    ['model'],
    buckets=[10, 25, 50, 75, 100, 150, 200, 300, 500]
)
```

---

**END OF PRD-004: ML ENSEMBLE ARCHITECTURE**

This document defines the complete ML system. Implementation modules will be created next.
