import logging

# import directly from your file location, e.g. agents.scalper.backtest.engine
from agents.scalper.backtest.engine import load_sample_data, run_simple_backtest

logging.basicConfig(level=logging.INFO)

class MinimalConfig:
    def __init__(self):
        self.backtest = {
            'slippage': 0.0005,
            'partial_fill_probability': 0.3,
            'partial_fill_min_pct': 0.65,
            'random_seed': 42,
            'walk_forward': {
                'enabled': False,
                'warmup_days': 3,
                'test_days': 2,
                'roll_bars': 24
            }
        }
        self.risk = type('Risk', (), {
            'global_max_drawdown': -0.15,
            'daily_stop_loss': -0.03,
            'max_concurrent_positions': 3,
            'per_symbol_max_exposure': 0.25,
            'circuit_breakers': {'spread_bps_max': 12}
        })()
        self.trading = type('Trading', (), {
            'position_sizing': {'base_position_size': 0.03}
        })()
        self.data = type('Data', (), {'warmup_bars': 50})()
        self.strategies = type('Strategies', (), {
            'scalp': type('Scalp', (), {
                'timeframe': '1m',
                'target_bps': 10,
                'stop_loss_bps': 5,
                'max_hold_seconds': 300,
                'max_spread_bps': 5,
                'post_only': True,
                'hidden_orders': False
            })()
        })()
        self.exchanges = {'kraken': type('Kraken', (), {'fee_taker': 0.0026})()}

def main():
    sample = load_sample_data(['BTC/USD'], '1m', days=7)
    cfg = MinimalConfig()
    res = run_simple_backtest(sample, pairs=['BTC/USD'], timeframe='1m', config=cfg, seed=42)
    print("\n== Smoke Result ==")
    print("total_trades:", res.summary['total_trades'])
    print("win_rate:", f"{res.summary['win_rate']:.1%}")
    print("total_return:", f"{res.summary['total_return']:.2%}")
    print("max_drawdown:", f"{res.summary['max_drawdown']:.2%}")
    print("final_equity:", f"${res.summary['final_equity']:,.2f}")

if __name__ == "__main__":
    main()
