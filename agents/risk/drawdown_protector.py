import json
from collections import defaultdict
from mcp.redis_manager import RedisManager
from config.config_loader import load_settings


class DrawdownProtector:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.trade_key = "mcp:trade_logs"
        self.flag_key = "mcp:strategy_flags"
        self.settings = load_settings()
        self.max_losses = self.settings.get("risk", {}).get("strategy_max_loss", {})

    def fetch_trade_logs(self):
        try:
            raw = self.redis.get(self.trade_key)
            return json.loads(raw) if raw else []
        except Exception as e:
            print(f"[❌] Failed to fetch trade logs: {e}")
            return []

    def check_drawdowns(self):
        logs = self.fetch_trade_logs()
        strategy_pnls = defaultdict(float)

        for trade in logs:
            strategy = trade.get("strategy")
            pnl = float(trade.get("pnl", 0))
            strategy_pnls[strategy] += pnl

        flagged = []
        for strategy, total_pnl in strategy_pnls.items():
            max_loss = self.max_losses.get(strategy, -1.0)
            if total_pnl < max_loss:
                flagged.append(strategy)

        if flagged:
            self.redis.set(self.flag_key, json.dumps(flagged))
            print(f"[⚠️] Strategies flagged for drawdown: {flagged}")
        else:
            self.redis.delete(self.flag_key)
            print("[✅] No strategies exceed drawdown limits.")

        return flagged


if __name__ == "__main__":
    protector = DrawdownProtector()
    protector.check_drawdowns()
