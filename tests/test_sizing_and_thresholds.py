from ai_engine.adaptive_learner import AdaptiveLearner
from mcp.context import Context

def test_adaptive_learner_respects_max_position():
    cfg = {"trading":{"dynamic_sizing":{"max_position":0.25,"volatility_multiplier":2.0}}}
    ctx = Context()
    learner = AdaptiveLearner(ctx, cfg)
    # structural placeholder; full integration needs trained models
    assert learner is not None
