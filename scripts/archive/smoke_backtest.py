from __future__ import annotations

"""
⚠️ SAFETY: No live trading unless MODE=live and confirmation set.
Smoke test for scalper backtest engine.
"""

import logging

# import directly from your file location, e.g. agents.scalper.backtest.engine
from agents.scalper.backtest.engine import load_sample_data, run_simple_backtest

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

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

def main() -> int:
    """Main entry point."""
    try:
        sample = load_sample_data(['BTC/USD'], '1m', days=7)
        cfg = MinimalConfig()
        res = run_simple_backtest(sample, pairs=['BTC/USD'], timeframe='1m', config=cfg, seed=42)
        logger.info("\n== Smoke Result ==")
        logger.info(f"total_trades: {res.summary['total_trades']}")
        logger.info(f"win_rate: {res.summary['win_rate']:.1%}")
        logger.info(f"total_return: {res.summary['total_return']:.2%}")
        logger.info(f"max_drawdown: {res.summary['max_drawdown']:.2%}")
        logger.info(f"final_equity: ${res.summary['final_equity']:,.2f}")
        return 0
    except Exception as e:
        logger.error(f"Smoke backtest failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
