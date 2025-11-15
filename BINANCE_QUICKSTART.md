# Binance Cross-Venue Integration - Quick Start

## TL;DR

```bash
# 1. Install SDK
pip install python-binance

# 2. Test connection
python scripts/test_binance_connection.py

# 3. Run monitor (single cycle)
python scripts/run_cross_venue_once.py

# 4. Run continuous monitoring
python agents/infrastructure/cross_venue_runner.py --symbols BTC/USD,ETH/USD
```

## What It Does

✅ Collects market data from Binance (READ-ONLY)
✅ Detects arbitrage opportunities (0.3-0.8% edge)
✅ Publishes AI features to Redis
✅ Emits Prometheus metrics

**Trading venue remains Kraken** - Binance is data-only.

## Quick Commands

### Test Binance Connection
```bash
python scripts/test_binance_connection.py
```

Expected output:
```
[OK] Binance reader initialized
[OK] Liquidity snapshot received
[OK] Ticker received
[OK] Funding rate received
[SUCCESS] All tests passed!
```

### Run Cross-Venue Monitor (Once)
```bash
python scripts/run_cross_venue_once.py
```

### Run Continuous Monitoring
```bash
# Default: BTC/USD, ETH/USD, SOL/USD @ 10s interval
python agents/infrastructure/cross_venue_runner.py

# Custom
python agents/infrastructure/cross_venue_runner.py \
  --symbols BTC/USD,ETH/USD,ADA/USD \
  --interval 15
```

### Run Tests
```bash
pytest tests/test_binance_integration.py -v
```

## Environment Variable

```bash
# Enable Binance reads (already set in scripts)
export EXTERNAL_VENUE_READS=binance
```

## Redis Streams

Data published to:
- `binance:liquidity:{symbol}`
- `binance:funding:{symbol}`
- `binance:ticker:{symbol}`
- `cross_venue:spread:{symbol}`
- `arbitrage:opportunity:{symbol}`
- `ai_features:cross_venue:{symbol}`

## AI Features

```json
{
  "symbol": "BTC/USD",
  "binance_liquidity_imbalance": 0.65,
  "binance_spread_bps": 2.5,
  "binance_funding_rate_annualized": 8.5,
  "cross_venue_arb_edge_bps": 35.8,
  "liquidity_imbalance_strength": 0.42
}
```

## Safety

✅ READ-ONLY - No Binance orders
✅ Feature flag - Disabled by default
✅ Conservative fees - 0.26% total
✅ Liquidity checks - $50k minimum

## Files

**Core:**
- `agents/infrastructure/binance_reader.py`
- `agents/infrastructure/cross_venue_analyzer.py`
- `agents/infrastructure/arbitrage_detector.py`
- `agents/infrastructure/cross_venue_runner.py`

**Tests:**
- `tests/test_binance_integration.py`
- `scripts/test_binance_connection.py`
- `scripts/run_cross_venue_once.py`

**Docs:**
- `BINANCE_CROSS_VENUE_GUIDE.md` - Full guide
- `BINANCE_INTEGRATION_COMPLETE.md` - Implementation summary
- `BINANCE_QUICKSTART.md` - This file

## Troubleshooting

**"Binance SDK not available"**
```bash
pip install python-binance
```

**"Binance reader disabled"**
```bash
export EXTERNAL_VENUE_READS=binance
```

**"No arbitrage opportunities"**
- Expected (Kraken data not integrated yet)
- Binance data is still being collected
- AI features are still published

## Next Steps

1. ✅ Test connection: `python scripts/test_binance_connection.py`
2. ✅ Run single cycle: `python scripts/run_cross_venue_once.py`
3. ⚠️  Integrate Kraken data (enable full cross-venue analysis)
4. 📊 Monitor metrics: Prometheus dashboard
5. 🤖 Consume AI features in signal processor

## Status

**Version:** 1.0.0
**Status:** ✅ OPERATIONAL
**Date:** 2025-11-08

---

For full documentation, see `BINANCE_CROSS_VENUE_GUIDE.md`
