# agents/selection/regime_adaptor.py
def adjust_for_regime(scores, current_regime):
    """Modify scores based on market regime"""
    if current_regime == 'bull':
        return scores * [1.2, 1.1, 0.9, 0.8]  # Boost momentum
    elif current_regime == 'bear':
        return scores * [0.8, 1.3, 1.1, 0.9]  # Boost reversion
    else:  # Sideways
        return scores * [0.9, 1.0, 1.2, 1.1]  # Boost sentiment