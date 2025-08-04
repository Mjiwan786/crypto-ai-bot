import os
import json
from mcp.redis_manager import RedisManager
from config.config_loader import load_settings


class ComplianceChecker:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.flag_key = "mcp:compliance_flags"
        self.settings = load_settings()
        self.rules = self.settings.get("risk", {}).get("compliance", {
            "restricted_assets": ["XMR", "USDT"],
            "restricted_regions": ["CN", "IR"],
            "restricted_exchanges": []
        })
        self.region = os.getenv("USER_REGION", "US")

    def fetch_open_positions(self):
        raw = self.redis.get("mcp:open_positions")
        return json.loads(raw) if raw else []

    def check_asset_restrictions(self, symbol):
        base = symbol.split("/")[0]
        return base in self.rules["restricted_assets"]

    def check_region(self):
        return self.region in self.rules["restricted_regions"]

    def check_exchange(self, exchange_id):
        return exchange_id in self.rules["restricted_exchanges"]

    def validate(self):
        positions = self.fetch_open_positions()
        flagged = []

        if self.check_region():
            flagged.append({"violation": "region", "region": self.region})

        for pos in positions:
            symbol = pos.get("symbol", "")
            exchange = pos.get("exchange", "kraken")

            if self.check_asset_restrictions(symbol):
                flagged.append({"violation": "asset", "symbol": symbol})
            if self.check_exchange(exchange):
                flagged.append({"violation": "exchange", "exchange": exchange})

        if flagged:
            self.redis.set(self.flag_key, json.dumps(flagged))
            print(f"[⚠️] Compliance violations detected: {flagged}")
        else:
            self.redis.delete(self.flag_key)
            print("[✅] No compliance issues.")

        return flagged


if __name__ == "__main__":
    cc = ComplianceChecker()
    cc.validate()
