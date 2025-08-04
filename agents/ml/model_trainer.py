import json
import os
import pandas as pd
import joblib
from datetime import datetime
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from mcp.redis_manager import RedisManager

class StrategyModelTrainer:
    def __init__(self):
        self.redis = RedisManager().connect()
        self.key = "mcp:trade_logs"
        self.model_path = "models/strategy_router_model.pkl"

    def load_trade_logs(self):
        try:
            raw = self.redis.get(self.key)
            logs = json.loads(raw) if raw else []
            return pd.DataFrame(logs)
        except Exception as e:
            print(f"[❌] Failed to load logs: {e}")
            return pd.DataFrame()

    def engineer_features(self, df):
        df['pnl_pct'] = df['pnl'] / (df['entry_price'] * df['quantity'] + 1e-9)
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['duration_min'] = df['duration_sec'] / 60
        df['win'] = df['pnl'] > 0
        features = df[['entry_price', 'exit_price', 'pnl_pct', 'duration_min', 'hour']]
        labels = df['strategy']
        return features, labels

    def train_model(self):
        df = self.load_trade_logs()
        if df.empty or len(df['strategy'].unique()) < 2:
            print("[⚠️] Not enough data to train model.")
            return None

        X, y = self.engineer_features(df)
        pipeline = Pipeline([
            ('scaler', StandardScaler()),
            ('clf', RandomForestClassifier(n_estimators=100, random_state=42))
        ])
        pipeline.fit(X, y)
        joblib.dump(pipeline, self.model_path)
        print(f"[✅] Trained & saved strategy selector model to {self.model_path}")
        return pipeline


if __name__ == "__main__":
    trainer = StrategyModelTrainer()
    trainer.train_model()
