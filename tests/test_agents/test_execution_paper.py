# tests/test_agents/test_execution_paper.py
from ai_engine.schemas import Signal
from agents.core.execution_agent import ExecutionAgent
def test_paper(fake_ex):
    ea = ExecutionAgent(fake_ex, {"bot":{"env":"paper"}})
    sig = Signal(strategy="breakout", exchange="kraken", symbol="ETH/USD", side="buy", confidence=0.8, size_quote_usd=50)
    t = ea.execute_signal(sig)
    assert t.status == "filled" and t.filled_amount > 0
