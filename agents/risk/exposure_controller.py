import json
from collections import defaultdict
from mcp.redis_manager import RedisManager
from config.config_loader import load_settings


class ExposureController:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.position_key = "mcp:open_positions"
        self.flag_key = "mcp:exposure_flags"
        self.settings = load_settings()
        self.exposure_limits = self.settings.get("risk", {}).get("exposure_limits", {
            "BTC": 0.4,
            "ETH": 0.4,
            "SOL": 0.25
        })

    def fetch_positions(self):
        raw = self.redis.get(self.position_key)
        return json.loads(raw) if raw else []

    def check_exposure(self):
        positions = self.fetch_positions()
        asset_exposure = defaultdict(float)

        for pos in positions:
            symbol = pos.get("symbol", "")
            base = symbol.split("/")[0]
            exposure = float(pos.get("value_usd", 0))
            asset_exposure[base] += exposure

        total = sum(asset_exposure.values())
        flags = []
        for asset, val in asset_exposure.items():
            limit = self.exposure_limits.get(asset, 0.3)
            percent = val / total if total else 0
            if percent > limit:
                flags.append({
                    "asset": asset,
                    "percent": round(percent, 2),
                    "limit": limit
                })

        if flags:
            self.redis.set(self.flag_key, json.dumps(flags))
            print(f"[⚠️] Exposure limit breached: {flags}")
        else:
            self.redis.delete(self.flag_key)
            print("[✅] No exposure issues detected.")

        return flags


if __name__ == "__main__":
    ec = ExposureController()
    ec.check_e_
