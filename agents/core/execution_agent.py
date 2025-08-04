import ccxt
import os
import redis
import json
from datetime import datetime
from mcp.redis_manager import RedisManager
from mcp.schemas import SignalScore
from config.config_loader import load_settings

class ExecutionAgent:
    def __init__(self):
        self.kraken = ccxt.kraken({
            'apiKey': os.getenv("KRAKEN_API_KEY"),
            'secret': os.getenv("KRAKEN_API_SECRET"),
        })
        self.redis = RedisManager().connect()
        self.settings = load_settings().get('trading', {})
        self.base_position_size = self.settings.get('base_position_size', 0.15)
        self.vol_multiplier = self.settings.get('dynamic_sizing', {}).get('volatility_multiplier', 1.0)
        self.max_position = self.settings.get('dynamic_sizing', {}).get('max_position', 0.3)
        self.min_confidence = self.settings.get('entry_conditions', {}).get('min_confidence', 0.75)

    def fetch_signals(self):
        raw = self.redis.get("mcp:signal_scores")
        if not raw:
            print("[⚠️] No signals found.")
            return []
        try:
            data = json.loads(raw)
            return [SignalScore(**d) for d in data if d['total_score'] >= self.min_confidence * 100]
        except Exception as e:
            print(f"[❌] Failed to parse signal data: {e}")
            return []

    def get_balance(self, currency='USD'):
        try:
            balance = self.kraken.fetch_balance()
            return balance[currency]['free']
        except Exception as e:
            print(f"[❌] Balance fetch error: {e}")
            return 0

    def execute_trade(self, symbol: str, score: float):
        base_currency = symbol.split('/')[0]
        quote_currency = symbol.split('/')[1]
        balance = self.get_balance(quote_currency)
        position_size = min(balance * self.base_position_size * self.vol_multiplier, balance * self.max_position)

        try:
            price = self.kraken.fetch_ticker(symbol)['ask']
            amount = position_size / price
            order = self.kraken.create_market_buy_order(symbol, amount)
            print(f"[✅] Executed BUY on {symbol}: {amount:.4f} at ${price}")
        except Exception as e:
            print(f"[❌] Execution failed for {symbol}: {e}")

    def run(self):
        print("[📤] Execution agent running...")
        signals = self.fetch_signals()
        for signal in signals:
            print(f"[⚙️] Evaluating {signal.symbol}: score={signal.total_score}")
            self.execute_trade(signal.symbol, signal.total_score)


if __name__ == "__main__":
    agent = ExecutionAgent()
    agent.run()
