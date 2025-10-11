"""
Risk Assessor Module for Short Selling Operations

Provides risk assessment capabilities for short-selling strategies including
position sizing, market risk evaluation, and portfolio risk management.
"""

from __future__ import annotations

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

try:
    from utils.logger import get_logger
except ImportError:
    def get_logger(name):
        return logging.getLogger(name)


@dataclass
class RiskMetrics:
    """Risk assessment metrics."""
    var_95: float  # Value at Risk 95%
    expected_shortfall: float  # Expected shortfall/CVaR
    max_drawdown: float  # Maximum drawdown
    sharpe_ratio: float  # Risk-adjusted return
    volatility: float  # Historical volatility
    correlation_risk: float  # Portfolio correlation risk
    liquidity_risk: float  # Liquidity risk score
    sentiment_risk: float  # Market sentiment risk


@dataclass
class PositionRisk:
    """Individual position risk assessment."""
    symbol: str
    position_size_usd: float
    leverage: float
    stop_loss_pct: float
    time_horizon_hours: float
    risk_score: float  # 0-1 scale
    risk_factors: List[str]


class RiskAssessor:
    """
    Comprehensive risk assessor for short-selling operations.
    
    Evaluates market risk, position risk, portfolio risk, and provides
    recommendations for position sizing and risk management.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize RiskAssessor.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger(__name__)
        
        # Risk thresholds from config
        self.max_position_risk = config.get("risk", {}).get("max_position_risk", 0.02)
        self.max_portfolio_risk = config.get("risk", {}).get("max_portfolio_risk", 0.05)
        self.max_correlation = config.get("risk", {}).get("max_correlation", 0.7)
        self.min_liquidity_score = config.get("risk", {}).get("min_liquidity_score", 0.3)
        
        # Volatility lookback periods
        self.vol_lookback_hours = config.get("risk", {}).get("volatility_lookback_hours", 168)  # 1 week
        
    def assess_position_risk(
        self,
        symbol: str,
        position_size_usd: float,
        market_data: Dict[str, Any],
        sentiment_data: Optional[Dict[str, Any]] = None
    ) -> PositionRisk:
        """
        Assess risk for an individual position.
        
        Args:
            symbol: Trading pair symbol
            position_size_usd: Position size in USD
            market_data: Market data including volatility, liquidity
            sentiment_data: Market sentiment indicators
            
        Returns:
            PositionRisk assessment
        """
        try:
            risk_factors = []
            
            # Calculate volatility risk
            volatility = market_data.get("volatility_24h", 0.02)
            if volatility > 0.05:  # 5% daily volatility threshold
                risk_factors.append("high_volatility")
            
            # Calculate liquidity risk
            liquidity_score = self._calculate_liquidity_score(market_data)
            if liquidity_score < self.min_liquidity_score:
                risk_factors.append("low_liquidity")
            
            # Calculate leverage risk
            leverage = market_data.get("leverage", 1.0)
            if leverage > 3.0:
                risk_factors.append("high_leverage")
            
            # Sentiment risk
            sentiment_risk = self._assess_sentiment_risk(sentiment_data)
            if sentiment_risk > 0.7:
                risk_factors.append("adverse_sentiment")
            
            # Market structure risk
            if market_data.get("funding_rate", 0) > 0.01:  # 1% funding rate
                risk_factors.append("expensive_short_funding")
            
            # Calculate overall risk score
            base_risk = min(volatility * 10, 1.0)  # Scale volatility to 0-1
            liquidity_penalty = max(0, (self.min_liquidity_score - liquidity_score) * 2)
            sentiment_penalty = sentiment_risk * 0.3
            
            risk_score = min(base_risk + liquidity_penalty + sentiment_penalty, 1.0)
            
            # Determine appropriate stop loss
            stop_loss_pct = max(0.02, volatility * 3)  # At least 2%, or 3x daily vol
            
            return PositionRisk(
                symbol=symbol,
                position_size_usd=position_size_usd,
                leverage=leverage,
                stop_loss_pct=stop_loss_pct,
                time_horizon_hours=24.0,  # Default 24h horizon
                risk_score=risk_score,
                risk_factors=risk_factors
            )
            
        except Exception as e:
            self.logger.error(f"Error assessing position risk for {symbol}: {e}")
            # Return high-risk assessment on error
            return PositionRisk(
                symbol=symbol,
                position_size_usd=position_size_usd,
                leverage=1.0,
                stop_loss_pct=0.05,
                time_horizon_hours=24.0,
                risk_score=1.0,  # Maximum risk
                risk_factors=["assessment_error"]
            )
    
    def calculate_portfolio_risk(
        self,
        positions: List[PositionRisk],
        market_correlations: Optional[Dict[str, Dict[str, float]]] = None
    ) -> RiskMetrics:
        """
        Calculate portfolio-level risk metrics.
        
        Args:
            positions: List of position risk assessments
            market_correlations: Correlation matrix between assets
            
        Returns:
            Portfolio risk metrics
        """
        try:
            if not positions:
                return self._empty_risk_metrics()
            
            # Calculate portfolio volatility
            portfolio_vol = self._calculate_portfolio_volatility(positions, market_correlations)
            
            # Calculate VaR and Expected Shortfall
            var_95 = portfolio_vol * 1.645  # 95% VaR assuming normal distribution
            expected_shortfall = portfolio_vol * 2.063  # ES at 95% confidence
            
            # Calculate maximum correlation risk
            max_correlation = self._calculate_max_correlation(positions, market_correlations)
            
            # Aggregate liquidity risk
            avg_liquidity_risk = sum(p.risk_score for p in positions) / len(positions)
            
            # Calculate aggregate sentiment risk
            sentiment_risk = min(sum(1 for p in positions if "adverse_sentiment" in p.risk_factors) / len(positions), 1.0)
            
            return RiskMetrics(
                var_95=var_95,
                expected_shortfall=expected_shortfall,
                max_drawdown=var_95 * 1.5,  # Estimate max drawdown
                sharpe_ratio=0.0,  # Would need return data to calculate
                volatility=portfolio_vol,
                correlation_risk=max_correlation,
                liquidity_risk=avg_liquidity_risk,
                sentiment_risk=sentiment_risk
            )
            
        except Exception as e:
            self.logger.error(f"Error calculating portfolio risk: {e}")
            return self._empty_risk_metrics()
    
    def recommend_position_size(
        self,
        symbol: str,
        account_balance: float,
        market_data: Dict[str, Any],
        target_risk: float = 0.01
    ) -> float:
        """
        Recommend position size based on risk budget.
        
        Args:
            symbol: Trading pair symbol
            account_balance: Account balance in USD
            market_data: Market data for risk calculation
            target_risk: Target risk as fraction of account (default 1%)
            
        Returns:
            Recommended position size in USD
        """
        try:
            # Get volatility for position sizing
            volatility = market_data.get("volatility_24h", 0.02)
            
            # Calculate position size using volatility targeting
            # target_risk = position_size * volatility / account_balance
            # Therefore: position_size = target_risk * account_balance / volatility
            
            base_position_size = target_risk * account_balance / volatility
            
            # Apply risk adjustments
            liquidity_score = self._calculate_liquidity_score(market_data)
            liquidity_adjustment = min(liquidity_score, 1.0)
            
            # Reduce size for high correlation assets (simplified)
            correlation_adjustment = 1.0  # Would need portfolio context
            
            # Apply maximum position size limits
            max_position_config = self.config.get("risk", {}).get("max_position_usd", 100000)
            max_position_pct = self.config.get("risk", {}).get("max_position_pct", 0.1)
            max_position_size = min(max_position_config, account_balance * max_position_pct)
            
            recommended_size = min(
                base_position_size * liquidity_adjustment * correlation_adjustment,
                max_position_size
            )
            
            self.logger.info(
                f"Position size recommendation for {symbol}: ${recommended_size:.2f} "
                f"(target_risk={target_risk:.3f}, volatility={volatility:.3f})"
            )
            
            return max(recommended_size, 100.0)  # Minimum $100 position
            
        except Exception as e:
            self.logger.error(f"Error recommending position size for {symbol}: {e}")
            return 1000.0  # Conservative fallback
    
    def check_risk_limits(self, position_risk: PositionRisk) -> Dict[str, bool]:
        """
        Check if position meets risk limits.
        
        Args:
            position_risk: Position risk assessment
            
        Returns:
            Dictionary of limit checks (True = within limits)
        """
        return {
            "position_risk_ok": position_risk.risk_score <= self.max_position_risk,
            "liquidity_ok": "low_liquidity" not in position_risk.risk_factors,
            "volatility_ok": "high_volatility" not in position_risk.risk_factors,
            "sentiment_ok": "adverse_sentiment" not in position_risk.risk_factors,
            "leverage_ok": position_risk.leverage <= 5.0,
            "stop_loss_reasonable": 0.01 <= position_risk.stop_loss_pct <= 0.1
        }
    
    def _calculate_liquidity_score(self, market_data: Dict[str, Any]) -> float:
        """Calculate liquidity score from market data."""
        try:
            # Use bid-ask spread and volume as liquidity proxies
            spread = market_data.get("spread_bps", 50) / 10000  # Convert bps to decimal
            volume_24h = market_data.get("volume_24h_usd", 1000000)
            
            # Normalize spread (lower spread = higher liquidity)
            spread_score = max(0, 1 - spread * 1000)  # Penalize wide spreads
            
            # Normalize volume (higher volume = higher liquidity)
            volume_score = min(volume_24h / 10000000, 1.0)  # $10M = perfect liquidity
            
            # Weighted average
            liquidity_score = 0.6 * spread_score + 0.4 * volume_score
            
            return max(0.0, min(1.0, liquidity_score))
            
        except Exception:
            return 0.5  # Default medium liquidity
    
    def _assess_sentiment_risk(self, sentiment_data: Optional[Dict[str, Any]]) -> float:
        """Assess sentiment risk (0 = low risk, 1 = high risk)."""
        if not sentiment_data:
            return 0.5  # Neutral risk when no data
        
        try:
            # Aggregate various sentiment indicators
            fear_greed = sentiment_data.get("fear_greed_index", 50) / 100
            social_sentiment = sentiment_data.get("social_sentiment", 0.5)
            funding_rates = sentiment_data.get("avg_funding_rate", 0)
            
            # High fear = good for shorts (low risk)
            # High greed = bad for shorts (high risk)
            sentiment_risk = fear_greed
            
            # Negative funding = expensive shorts (high risk)
            if funding_rates < -0.01:
                sentiment_risk += 0.3
            
            return max(0.0, min(1.0, sentiment_risk))
            
        except Exception:
            return 0.5
    
    def _calculate_portfolio_volatility(
        self,
        positions: List[PositionRisk],
        correlations: Optional[Dict[str, Dict[str, float]]]
    ) -> float:
        """Calculate portfolio volatility considering correlations."""
        if not positions:
            return 0.0
        
        # Simple portfolio volatility calculation
        # In practice, would use covariance matrix
        weights = [p.position_size_usd for p in positions]
        total_size = sum(weights)
        weights = [w / total_size for w in weights]
        
        # Assume individual asset volatilities (would get from market data)
        asset_vols = [0.02 * (1 + p.risk_score) for p in positions]  # Base 2% + risk adjustment
        
        if not correlations:
            # Uncorrelated portfolio
            portfolio_var = sum(w**2 * vol**2 for w, vol in zip(weights, asset_vols))
        else:
            # Would implement full covariance calculation here
            portfolio_var = sum(w**2 * vol**2 for w, vol in zip(weights, asset_vols))
        
        return portfolio_var ** 0.5
    
    def _calculate_max_correlation(
        self,
        positions: List[PositionRisk],
        correlations: Optional[Dict[str, Dict[str, float]]]
    ) -> float:
        """Calculate maximum correlation in portfolio."""
        if not correlations or len(positions) < 2:
            return 0.0
        
        max_corr = 0.0
        symbols = [p.symbol for p in positions]
        
        for i, sym1 in enumerate(symbols):
            for sym2 in symbols[i+1:]:
                corr = correlations.get(sym1, {}).get(sym2, 0.0)
                max_corr = max(max_corr, abs(corr))
        
        return max_corr
    
    def _empty_risk_metrics(self) -> RiskMetrics:
        """Return empty risk metrics."""
        return RiskMetrics(
            var_95=0.0,
            expected_shortfall=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            volatility=0.0,
            correlation_risk=0.0,
            liquidity_risk=0.0,
            sentiment_risk=0.5
        )