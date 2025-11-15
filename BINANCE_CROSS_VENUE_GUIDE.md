# Binance Cross-Venue Integration Guide

## Overview

The Binance cross-venue integration provides **READ-ONLY** market data collection and analysis for arbitrage detection. This system:

- Collects liquidity snapshots from Binance
- Compares prices across Binance and Kraken
- Detects arbitrage opportunities (0.3-0.8% edge target)
- Publishes signals to AI features namespace
- **DOES NOT PLACE ORDERS** on Binance

Trading venue remains **Kraken only** for now.

## Features

✅ **Binance Market Data Reader**
- Order book liquidity snapshots
- Funding rates (perpetual futures)
- 24h ticker statistics
- Real-time via Binance REST API

✅ **Cross-Venue Analysis**
- Price spread detection (Binance vs Kraken)
- Liquidity imbalance divergence
- Funding rate differentials
- Arbitrage opportunity scoring

✅ **Arbitrage Detector (Stub)**
- Detects opportunities with 0.3%+ edge
- Tracks opportunity duration
- Emits Prometheus metrics
- **No order placement** (detection only)

✅ **AI Feature Integration**
- Publishes to Redis streams
- Features: liquidity_imbalance, funding_arb, cross_venue_spread
- Ready for ML model consumption

## Architecture

```
┌─────────────────┐       ┌─────────────────┐
│  Binance Reader │       │  Kraken Data    │
│  (READ-ONLY)    │       │  (Existing)     │
└────────┬────────┘       └────────┬────────┘
         │                         │
         └────────┬────────────────┘
                  │
         ┌────────▼────────┐
         │ Cross-Venue     │
         │ Analyzer        │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ Arbitrage       │
         │ Detector (Stub) │
         └────────┬────────┘
                  │
         ┌────────▼────────┐
         │ AI Features     │
         │ (Redis Streams) │
         └─────────────────┘
```

## Setup

### 1. Install Binance SDK

```bash
conda activate crypto-bot
pip install python-binance
```

### 2. Set Environment Variable

```bash
# Enable Binance data reads
export EXTERNAL_VENUE_READS=binance

# Optional: Binance API credentials (not required for public data)
export BINANCE_API_KEY=your_key_here
export BINANCE_API_SECRET=your_secret_here
```

### 3. Configure Redis

The system uses the existing Redis Cloud connection:

```bash
export REDIS_URL="rediss://default:Salam78614**$$@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818"
```

Certificate path:
```
C:\Users\Maith\OneDrive\Desktop\crypto_ai_bot\config\certs\redis_ca.pem
```

## Usage

### Run Cross-Venue Monitor

```bash
# Continuous monitoring (default: 10s interval)
python agents/infrastructure/cross_venue_runner.py

# Custom symbols and interval
python agents/infrastructure/cross_venue_runner.py \
  --symbols BTC/USD,ETH/USD,SOL/USD,ADA/USD \
  --interval 15

# Run once and exit
python agents/infrastructure/cross_venue_runner.py --once
```

### Programmatic Usage

```python
from agents.infrastructure.binance_reader import BinanceReader
from agents.infrastructure.cross_venue_analyzer import CrossVenueAnalyzer
from agents.infrastructure.arbitrage_detector import ArbitrageDetector

# Initialize components
binance_reader = BinanceReader()
analyzer = CrossVenueAnalyzer()
detector = ArbitrageDetector(
    binance_reader=binance_reader,
    cross_venue_analyzer=analyzer,
)

# Collect data
binance_data = binance_reader.get_all_symbols_data(["BTC/USD", "ETH/USD"])
kraken_data = {}  # From existing Kraken source

# Analyze
opportunities = analyzer.get_arbitrage_opportunities(
    symbols=["BTC/USD", "ETH/USD"],
    binance_data_map=binance_data,
    kraken_data_map=kraken_data,
)

# Print opportunities
for opp in opportunities:
    print(f"{opp.symbol}: {opp.net_edge_bps:.1f}bps edge ({opp.direction})")
```

## Data Structures

### BinanceLiquiditySnapshot

```python
@dataclass
class BinanceLiquiditySnapshot:
    symbol: str
    timestamp: float
    best_bid: float
    best_ask: float
    bid_volume: float
    ask_volume: float
    spread_bps: float
    bid_depth_usd: float
    ask_depth_usd: float
    imbalance_ratio: float  # 0.0 to 1.0
```

### CrossVenueSpread

```python
@dataclass
class CrossVenueSpread:
    symbol: str
    timestamp: float
    binance_bid: float
    binance_ask: float
    kraken_bid: float
    kraken_ask: float
    spread_bps: float
    arb_direction: VenueArbitrageDirection
    gross_edge_bps: float  # Before fees
    net_edge_bps: float    # After fees
    is_arbitrageable: bool  # net_edge_bps >= 30
```

### ArbitrageOpportunity

```python
@dataclass
class ArbitrageOpportunity:
    opportunity_id: str
    symbol: str
    detected_at: float
    direction: str
    gross_edge_bps: float
    net_edge_bps: float
    binance_price: float
    kraken_price: float
    estimated_size_usd: float
    confidence: float  # 0.0 to 1.0
    is_active: bool
```

## Redis Streams

### Published Streams

1. **Binance Market Data**
   - `binance:liquidity:{symbol}` - Liquidity snapshots
   - `binance:funding:{symbol}` - Funding rates
   - `binance:ticker:{symbol}` - 24h statistics

2. **Cross-Venue Signals**
   - `cross_venue:spread:{symbol}` - Price spreads
   - `cross_venue:liquidity_imbalance:{symbol}` - Imbalance signals
   - `cross_venue:funding:{symbol}` - Funding differentials

3. **Arbitrage Opportunities**
   - `arbitrage:opportunity:{symbol}` - New opportunities
   - `arbitrage:summary` - Summary of all opportunities

4. **AI Features**
   - `ai_features:cross_venue:{symbol}` - ML-ready features

### AI Features Schema

```json
{
  "symbol": "BTC/USD",
  "timestamp": 1699999999.0,
  "binance_liquidity_imbalance": 0.65,
  "binance_spread_bps": 2.5,
  "binance_bid_depth_usd": 250000.0,
  "binance_ask_depth_usd": 230000.0,
  "binance_funding_rate_annualized": 8.5,
  "cross_venue_spread_bps": 5.2,
  "cross_venue_arb_edge_bps": 35.8,
  "cross_venue_arb_opportunity": true,
  "liquidity_imbalance_divergence": 0.15,
  "liquidity_imbalance_strength": 0.42
}
```

## Metrics

### Prometheus Metrics

The system exposes the following metrics:

```
# Arbitrage opportunities
arbitrage_opportunities_detected_total{symbol, direction}
arbitrage_opportunities_active
arbitrage_edge_bps (histogram)
arbitrage_opportunity_duration_seconds (histogram)

# Liquidity
liquidity_imbalance_strength (histogram)
```

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `EXTERNAL_VENUE_READS` | `""` | Set to `"binance"` to enable |
| `BINANCE_API_KEY` | `""` | Binance API key (optional) |
| `BINANCE_API_SECRET` | `""` | Binance API secret (optional) |
| `REDIS_URL` | From .env | Redis connection URL |

### Thresholds

**Arbitrage Detection:**
- Minimum edge: 0.3% (30 bps)
- Target edge: 0.8% (80 bps)
- Minimum confidence: 0.7
- Minimum liquidity: $50,000 per side

**Fees (Conservative):**
- Binance: 0.10% (10 bps)
- Kraken: 0.16% (16 bps taker)
- Total: 0.26% (26 bps)

**Update Intervals:**
- Liquidity snapshots: 10s
- Funding rates: 300s (cached)
- Arbitrage detection: 10s

## Testing

### Run Tests

```bash
# All Binance integration tests
python -m pytest tests/test_binance_integration.py -v

# Specific test class
python -m pytest tests/test_binance_integration.py::TestBinanceReader -v

# With coverage
python -m pytest tests/test_binance_integration.py --cov=agents.infrastructure --cov-report=html
```

### Test Coverage

Tests include:
- Feature flag on/off paths
- Market data collection
- Cross-venue spread calculation
- Liquidity imbalance detection
- Arbitrage opportunity detection
- Confidence scoring
- AI feature publishing

## Example Outputs

### Arbitrage Opportunity Log

```
INFO - NEW ARBITRAGE OPPORTUNITY: BTC/USD (buy_binance_sell_kraken) -
  Edge: 42.3bps, Confidence: 0.85, Size: $125,000
```

### Opportunity Summary

```json
{
  "active_count": 2,
  "total_detected": 15,
  "avg_edge_bps": 38.5,
  "max_edge_bps": 52.1,
  "opportunities": [
    {
      "symbol": "BTC/USD",
      "direction": "buy_binance_sell_kraken",
      "net_edge_bps": 42.3,
      "confidence": 0.85,
      "estimated_size_usd": 125000.0
    },
    {
      "symbol": "ETH/USD",
      "direction": "buy_kraken_sell_binance",
      "net_edge_bps": 34.7,
      "confidence": 0.78,
      "estimated_size_usd": 95000.0
    }
  ]
}
```

## Integration with Existing System

### AI Feature Consumption

The cross-venue signals are published to Redis and can be consumed by:

1. **Signal Processor** - Include in enhanced signals
2. **Regime Detector** - Cross-venue divergence as regime indicator
3. **Strategy Router** - Route based on arbitrage opportunities
4. **Risk Manager** - Consider cross-venue liquidity

Example integration:

```python
# In signal_processor.py
def process_enhanced_signal(self, signal):
    # Get cross-venue features
    cv_features = self.redis.get_latest_event(
        f"ai_features:cross_venue:{signal.symbol}"
    )

    if cv_features:
        # Boost confidence if arbitrage exists
        if cv_features.get("cross_venue_arb_opportunity"):
            signal.confidence *= 1.1

        # Add liquidity imbalance signal
        signal.liquidity_strength = cv_features.get(
            "liquidity_imbalance_strength", 0.0
        )
```

### Kraken Data Integration

To complete cross-venue analysis, integrate existing Kraken data:

```python
# In cross_venue_runner.py
def collect_kraken_data(self) -> Dict[str, Dict]:
    # Option 1: From WebSocket cache
    kraken_data = {}
    for symbol in self.symbols:
        orderbook = self.kraken_ws.get_orderbook(symbol)
        if orderbook:
            kraken_data[symbol] = {
                "liquidity": self._parse_kraken_orderbook(orderbook)
            }

    # Option 2: From Redis cache
    # kraken_data = self.redis.get_cached_kraken_data(symbols)

    return kraken_data
```

## Safety and Limitations

### Safety Features

✅ **READ-ONLY** - No order placement on Binance
✅ **Feature Flag** - Disabled by default
✅ **Conservative Fees** - Overestimates transaction costs
✅ **Confidence Scoring** - Filters low-quality opportunities
✅ **Liquidity Checks** - Requires minimum depth

### Current Limitations

⚠️ **Kraken Data** - Not yet integrated (placeholder)
⚠️ **Funding Rates** - Binance only (Kraken futures not integrated)
⚠️ **Latency** - 10s polling interval (not tick-by-tick)
⚠️ **Order Execution** - Detection only, no auto-execution

### Future Enhancements

- [ ] Integrate Kraken order book data
- [ ] Add WebSocket streams (lower latency)
- [ ] Include transaction costs (withdrawal fees)
- [ ] Add order execution module (when ready)
- [ ] Support more venues (Coinbase, FTX)
- [ ] Historical arbitrage analysis

## Troubleshooting

### Issue: "Binance reader disabled"

**Cause:** Feature flag not set

**Solution:**
```bash
export EXTERNAL_VENUE_READS=binance
python agents/infrastructure/cross_venue_runner.py
```

### Issue: "Binance SDK not available"

**Cause:** python-binance not installed

**Solution:**
```bash
conda activate crypto-bot
pip install python-binance
```

### Issue: "No arbitrage opportunities found"

**Cause:** Markets are efficient or insufficient data

**Solutions:**
1. Check Kraken data integration
2. Lower minimum edge threshold
3. Increase update frequency
4. Verify both venues have data

### Issue: "Redis connection failed"

**Cause:** Invalid Redis URL or certificate

**Solution:**
```bash
# Verify Redis URL
echo $REDIS_URL

# Test connection
redis-cli -u $REDIS_URL --tls --cacert config/certs/redis_ca.pem ping
```

## Best Practices

1. **Monitor Continuously** - Run in background for best detection
2. **Review Logs** - Check for API errors or rate limits
3. **Validate Opportunities** - Always verify before considering execution
4. **Update Fees** - Keep fee assumptions current
5. **Test Thoroughly** - Use `--once` mode for testing

## Support

For issues or questions:
1. Check logs: `logs/cross_venue.log`
2. Review metrics: Prometheus dashboard
3. Check Redis streams: `redis-cli XREAD ...`
4. Run tests: `pytest tests/test_binance_integration.py -v`

## Author

Crypto AI Bot Team

## Last Updated

2025-11-08
