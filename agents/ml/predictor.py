import joblib
import pandas as pd
from datetime import datetime
from mcp.redis_manager import RedisManager
from mcp.schemas import MarketContext


class StrategyPredictor:
    def __init__(self, model_path="models/strategy_router_model.pkl"):
        self.redis = RedisManager().connect()
        self.model_path = model_path
        self.model = joblib.load(self.model_path)

    def fetch_market_context(self):
        try:
            raw = self.redis.get("mcp:market_context")
            if not raw:
                print("[⚠️] No market context available.")
                return None
            return MarketContext.model_validate_json(raw)
        except Exception as e:
            print(f"[❌] Error loading market context: {e}")
            return None

    def extract_features(self, opportunity):
        now = datetime.utcnow()
        # Dummy features — replace with real logic if available
        entry_price = 1.0
        exit_price = 1.01
        pnl_pct = 0.01
        duration_min = 5
        hour = now.hour

        return pd.DataFrame([{
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "duration_min": duration_min,
            "hour": hour
        }])

    def predict_strategy(self):
        context = self.fetch_market_context()
        if not context or not context.market_opportunities:
            print("[⚠️] No market opportunities found.")
            return None

        scores = []
        for opp in context.market_opportunities[:3]:  # top 3 opportunities
            features = self.extract_features(opp)
            prediction = self.model.predict(features)[0]
            probas = self.model.predict_proba(features)
            scores.append({
                "symbol": opp.symbol,
                "recommended_strategy": prediction,
                "confidence": round(max(probas[0]), 2)
            })

        return scores


if __name__ == "__main__":
    predictor = StrategyPredictor()
    results = predictor.predict_strategy()
    print("[🔍] Predicted Strategy Allocation:")
    for r in results:
        print(r)
