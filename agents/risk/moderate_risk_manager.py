import json
from mcp.redis_manager import RedisManager

class ModerateRiskManager:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.output_key = "mcp:risk_health"

    def fetch_flag(self, key):
        raw = self.redis.get(key)
        return json.loads(raw) if raw else []

    def assess_risk(self):
        flags = {
            "drawdown": self.fetch_flag("mcp:strategy_flags"),
            "exposure": self.fetch_flag("mcp:exposure_flags"),
            "compliance": self.fetch_flag("mcp:compliance_flags")
        }

        health_status = "healthy"
        total_flags = sum(len(v) for v in flags.values())

        if total_flags >= 3:
            health_status = "critical"
        elif total_flags == 2:
            health_status = "elevated"
        elif total_flags == 1:
            health_status = "watch"

        summary = {
            "status": health_status,
            "flag_count": total_flags,
            "details": flags
        }

        self.redis.set(self.output_key, json.dumps(summary))
        print(f"[🧠] Risk health summary: {summary}")
        return summary


if __name__ == "__main__":
    mgr = ModerateRiskManager()
    mgr.assess_risk()
