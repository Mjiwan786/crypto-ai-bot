
def test_strategy_selector():
    import sys
    import os
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
    from ai_engine.strategy_selector import StrategySelector
    selector = StrategySelector()
    assert selector.select_strategy("bull") == "trend_following"
