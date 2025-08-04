import json
from mcp.redis_manager import RedisManager
from config.config_loader import load_settings


class PortfolioBalancer:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.alloc_key = "mcp:strategy_allocation"
        self.flag_key = "mcp:strategy_flags"
        self.output_key = "mcp:capital_allocation"
        self.settings = load_settings()
        self.default_alloc = self.settings.get("strategies", {}).get("allocations", {})

    def fetch_strategy_allocation(self):
        raw = self.redis.get(self.alloc_key)
        if not raw:
            print("[ℹ️] Using default allocations from settings.yaml")
            return self.default_alloc
        return json.loads(raw)

    def fetch_flagged_strategies(self):
        raw = self.redis.get(self.flag_key)
        return json.loads(raw) if raw else []

    def apply_risk_filters(self, allocation, flagged):
        filtered = {
            k: v for k, v in allocation.items()
            if k not in flagged
        }
        if not filtered:
            print("[⚠️] All strategies are flagged. Using conservative fallback.")
            return {k: 1.0 / len(self.default_alloc) for k in self.default_alloc}
        total = sum(filtered.values())
        return {k: round(v / total, 2) for k, v in filtered.items()}

    def balance(self):
        alloc = self.fetch_strategy_allocation()
        flagged = self.fetch_flagged_strategies()
        final_alloc = self.apply_risk_filters(alloc, flagged)

        self.redis.set(self.output_key, json.dumps(final_alloc))
        print(f"[✅] Capital allocation stored: {final_alloc}")
        return final_alloc


if __name__ == "__main__":
    balancer = PortfolioBalancer()
    balancer.balance()
