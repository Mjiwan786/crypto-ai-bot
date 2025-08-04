import redis
import json
from collections import Counter
from mcp.redis_manager import RedisManager
from agents.ml.predictor import StrategyPredictor


class StrategySelector:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.predictor = StrategyPredictor()
        self.redis_key = "mcp:strategy_allocation"

    def allocate_strategies(self):
        predictions = self.predictor.predict_strategy()
        if not predictions:
            print("[⚠️] No predictions available.")
            return {}

        # Count strategies and normalize to weights
        strategy_counts = Counter(p['recommended_strategy'] for p in predictions)
        total = sum(strategy_counts.values())
        allocation = {k: round(v / total, 2) for k, v in strategy_counts.items()}

        self.redis.set(self.redis_key, json.dumps(allocation))
        print(f"[✅] Strategy allocation stored in Redis: {allocation}")
        return allocation


if __name__ == "__main__":
    selector = StrategySelector()
    selector.allocate_strategies()
