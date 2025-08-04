import redis
import json
import os
from datetime import datetime
from mcp.redis_manager import RedisManager


class PerformanceMonitor:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.key = "mcp:trade_logs"

    def log_trade_result(self, symbol, entry_price, exit_price, quantity, strategy, pnl, duration_sec):
        trade_record = {
            "timestamp": datetime.utcnow().isoformat(),
            "symbol": symbol,
            "strategy": strategy,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "quantity": quantity,
            "pnl": pnl,
            "duration_sec": duration_sec,
        }

        try:
            existing = self.redis.get(self.key)
            logs = json.loads(existing) if existing else []
            logs.append(trade_record)
            self.redis.set(self.key, json.dumps(logs))
            print(f"[📈] Logged trade for {symbol}: PnL={pnl:.2f}")
        except Exception as e:
            print(f"[❌] Failed to log trade: {e}")

    def get_trade_logs(self):
        try:
            raw = self.redis.get(self.key)
            return json.loads(raw) if raw else []
        except Exception as e:
            print(f"[❌] Failed to retrieve logs: {e}")
            return []

    def get_summary(self):
        trades = self.get_trade_logs()
        if not trades:
            return {"count": 0, "pnl_total": 0.0, "avg_duration_sec": 0}

        pnl_total = sum(t['pnl'] for t in trades)
        avg_duration = sum(t['duration_sec'] for t in trades) / len(trades)
        return {
            "count": len(trades),
            "pnl_total": round(pnl_total, 2),
            "avg_duration_sec": round(avg_duration, 2)
        }


if __name__ == "__main__":
    monitor = PerformanceMonitor()
    summary = monitor.get_summary()
    print("[📊] Performance Summary:")
    print(summary)
