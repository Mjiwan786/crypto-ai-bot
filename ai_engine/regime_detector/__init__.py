def infer_regime(trend_strength: float, bb_width: float, sentiment: float) -> str:
    # tweak these thresholds later
    if trend_strength > 0.6 and sentiment >= 0:
        return "bull"
    if trend_strength < 0.35 and sentiment <= 0:
        return "bear"
    return "sideways"
