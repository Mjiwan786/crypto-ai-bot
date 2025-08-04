# agents/selection/portfolio_optimizer.py
import numpy as np
import pandas as pd
from pypfopt import EfficientFrontier, risk_models

class PortfolioOptimizer:
    def __init__(self):
        self.risk_free_rate = 0.05  # 5% annualized
    
    def build_portfolio(self, scored_coins, max_positions=8):
        """Construct optimized portfolio from top coins"""
        df = pd.DataFrame(scored_coins).T
        df = df.nlargest(50, 'composite')  # Top 50 by score
        
        # Calculate covariance matrix
        returns = df.pivot_table(index='date', columns='symbol', values='return')
        cov_matrix = risk_models.exp_cov(returns)
        
        # Mean-variance optimization
        ef = EfficientFrontier(
            df['composite'],  # Using ML score as expected return
            cov_matrix,
            weight_bounds=(0.01, 0.3)  # Min 1%, max 30% per coin
        )
        ef.max_sharpe(risk_free_rate=self.risk_free_rate)
        weights = ef.clean_weights()
        
        # Select top coins meeting criteria
        portfolio = {
            sym: wt for sym, wt in weights.items() 
            if wt > 0.05  # At least 5% allocation
        }
        
        return dict(sorted(portfolio.items(), key=lambda x: x[1], reverse=True)[:max_positions])