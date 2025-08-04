from pydantic import BaseModel, Field
from typing import List, Optional

class MeanReversionConfig(BaseModel):
    enabled: bool
    rsi_period: int
    rsi_buy_threshold: float
    rsi_sell_threshold: float
    distance_to_ma_period: int
    bollinger_band_period: int
    bollinger_band_stddev: float

class TrendFollowingConfig(BaseModel):
    enabled: bool
    ma_period: int
    breakout_threshold: float

class BreakoutConfig(BaseModel):
    enabled: bool
    breakout_length: int
    breakout_multiplier: float

# Similar classes for TrendFollowingConfig, BreakoutConfig...

class StrategySettings(BaseModel):
    active: List[str]
    mean_reversion: Optional[MeanReversionConfig]
    trend_following: Optional[TrendFollowingConfig]
    breakout: Optional[BreakoutConfig]