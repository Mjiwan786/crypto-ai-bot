import pandas as pd
import numpy as np
from datetime import datetime

class FeatureEngineer:
    def __init__(self):
        pass

    def from_trade_logs(self, df: pd.DataFrame) -> pd.DataFrame:
        df['pnl_pct'] = df['pnl'] / (df['entry_price'] * df['quantity'] + 1e-9)
        df['hour'] = pd.to_datetime(df['timestamp']).dt.hour
        df['duration_min'] = df['duration_sec'] / 60.0
        df['volatility'] = np.abs(df['entry_price'] - df['exit_price']) / df['entry_price']
        return df[[
            'entry_price', 'exit_price', 'pnl_pct',
            'duration_min', 'hour', 'volatility'
        ]]

    def from_market_opportunity(self, opp, timestamp=None) -> pd.DataFrame:
        """
        Translates a MarketOpportunity into a feature row.
        Extend this logic with real TA or sentiment features in production.
        """
        ts = timestamp or datetime.utcnow()
        hour = ts.hour

        # Dummy values — replace with real indicators, sentiment, etc.
        entry_price = 1.0
        exit_price = 1.01
        pnl_pct = 0.01
        duration_min = 5.0
        volatility = 0.002

        return pd.DataFrame([{
            "entry_price": entry_price,
            "exit_price": exit_price,
            "pnl_pct": pnl_pct,
            "duration_min": duration_min,
            "hour": hour,
            "volatility": volatility
        }])
