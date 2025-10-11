import pandas as pd
import pytest

# Adjust import to your module path
from agents.scalper.backtest.engine import (
    load_sample_data,
    validate_backtest_data,
    BacktestEngine,
    ScalperAdapter,
    Candle,
    Order, OrderType, Side, intrabar_fillable,
)

class MinimalConfig:
    def __init__(self,
                 walk_forward_enabled=False,
                 warmup_bars=50,
                 base_pos=0.03,
                 target_bps=10,
                 stop_bps=5):
        self.backtest = {
            'slippage': 0.0005,
            'partial_fill_probability': 0.0,  # deterministic fills for tests
            'partial_fill_min_pct': 1.0,
            'random_seed': 42,
            'walk_forward': {
                'enabled': walk_forward_enabled,
                'warmup_days': 2,
                'test_days': 1,
                'roll_bars': 60
            }
        }
        self.risk = type('Risk', (), {
            'global_max_drawdown': -0.50,
            'daily_stop_loss': -0.20,
            'max_concurrent_positions': 10,
            'per_symbol_max_exposure': 1.00,
            'circuit_breakers': {'spread_bps_max': 50}
        })()
        self.trading = type('Trading', (), {
            'position_sizing': {'base_position_size': base_pos}
        })()
        self.data = type('Data', (), {'warmup_bars': warmup_bars})()
        self.strategies = type('Strategies', (), {
            'scalp': type('Scalp', (), {
                'timeframe': '1m',
                'target_bps': target_bps,
                'stop_loss_bps': stop_bps,
                'max_hold_seconds': 300,
                'max_spread_bps': 50,
                'post_only': False,
                'hidden_orders': False
            })()
        })()
        self.exchanges = {'kraken': type('Kraken', (), {'fee_taker': 0.0026})()}

@pytest.fixture(scope="module")
def sample_data():
    return load_sample_data(['BTC/USD', 'ETH/USD'], '1m', days=3)

def test_sample_data_generation(sample_data):
    assert 'BTC/USD@1m' in sample_data
    btc = sample_data['BTC/USD@1m']
    assert isinstance(btc.index, pd.DatetimeIndex)
    assert {'open','high','low','close','volume'}.issubset(btc.columns)
    assert len(btc) > 1000  # 3 days * 1440 min = 4320 bars

def test_validate_backtest_data(sample_data):
    report = validate_backtest_data(sample_data, min_bars=100)
    assert report['valid'] is True
    for key, info in report['data_summary'].items():
        assert info['bars'] >= 100

def test_intrabar_limit_fill_logic():
    ts = pd.Timestamp.utcnow(tz='UTC')
    c = Candle(ts, open=100, high=105, low=95, close=102, volume=10_000)
    # Buy limit at/below low should fill
    o1 = Order("1", ts, "X/Y", Side.BUY, OrderType.LIMIT, qty=1.0, limit_price=96)
    can_fill, price = intrabar_fillable(o1, c)
    assert can_fill and 95 <= price <= 105
    # Sell limit at/above high should fill
    o2 = Order("2", ts, "X/Y", Side.SELL, OrderType.LIMIT, qty=1.0, limit_price=104)
    can_fill, price = intrabar_fillable(o2, c)
    assert can_fill and 95 <= price <= 105
    # Post‑only should block if crossing
    o3 = Order("3", ts, "X/Y", Side.BUY, OrderType.LIMIT, qty=1.0, limit_price=99, post_only=True)
    # open < limit => would cross -> expect False
    can_fill, _ = intrabar_fillable(o3, c)
    assert can_fill is False

def test_engine_single_run_smoke(sample_data):
    cfg = MinimalConfig(walk_forward_enabled=False, warmup_bars=50, base_pos=0.02)
    engine = BacktestEngine(cfg, seed=42)
    engine.load_ohlcv(sample_data)
    adapter = ScalperAdapter(cfg)
    result = engine.run(['BTC/USD'], '1m', adapter, walk_forward=False)
    # Result structure
    assert isinstance(result.summary, dict)
    assert 'final_equity' in result.summary
    assert result.summary['starting_cash'] == 100000.0
    # Deterministic seed should yield stable equity range
    assert 80000 <= result.summary['final_equity'] <= 120000

def test_engine_walk_forward(sample_data):
    cfg = MinimalConfig(walk_forward_enabled=True, warmup_bars=50, base_pos=0.02)
    engine = BacktestEngine(cfg, seed=123)
    engine.load_ohlcv(sample_data)
    adapter = ScalperAdapter(cfg)
    res = engine.run(['BTC/USD'], '1m', adapter, walk_forward=True)
    assert res.metadata.get('walk_forward') is True
    assert res.summary.get('walk_forward_windows', 0) >= 1

def test_risk_circuit_breakers_trigger_fast(sample_data):
    # Force tight circuit breakers to trip
    cfg = MinimalConfig(walk_forward_enabled=False, warmup_bars=50, base_pos=0.5)
    cfg.risk.global_max_drawdown = -0.01  # 1% DD
    cfg.risk.daily_stop_loss = -0.005     # 0.5% daily
    engine = BacktestEngine(cfg, seed=7)
    engine.load_ohlcv(sample_data)
    adapter = ScalperAdapter(cfg)
