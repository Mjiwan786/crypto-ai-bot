# agents/selection/coin_ranker.py
import joblib
import numpy as np
from sklearn.ensemble import VotingRegressor

class CoinRanker:
    def __init__(self):
        self.models = {
            'momentum': joblib.load('models/momentum_scorer.pkl'),
            'reversion': joblib.load('models/mean_reversion_scorer.pkl'),
            'sentiment': joblib.load('models/sentiment_scorer.pkl'),
            'liquidity': joblib.load('models/liquidity_scorer.pkl')
        }
        
        self.weights = {
            'momentum': 0.35,
            'reversion': 0.25,
            'sentiment': 0.20,
            'liquidity': 0.20
        }
    
    def score_coins(self, coin_data):
        """Generate composite scores for all coins"""
        scores = {}
        
        for symbol, data in coin_data.items():
            # Get predictions from each model
            model_scores = {}
            for name, model in self.models.items():
                features = self._prepare_features(name, data)
                model_scores[name] = model.predict([features])[0]
            
            # Calculate weighted composite score
            composite = sum(
                model_scores[name] * weight 
                for name, weight in self.weights.items()
            )
            
            scores[symbol] = {
                'composite': composite,
                **model_scores,
                **data
            }
        
        return scores
    
    def _prepare_features(self, model_name, coin_data):
        """Prepare model-specific features"""
        if model_name == 'momentum':
            return [
                coin_data['1w_return'],
                coin_data['1m_return'],
                coin_data['volume_spike']
            ]
        elif model_name == 'reversion':
            return [
                coin_data['rsi_14'],
                coin_data['distance_to_ma'],
                coin_data['bollinger_pct']
            ]
        # ... other feature preparations