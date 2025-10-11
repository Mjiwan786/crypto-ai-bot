# tests/test_agents/test_execution_risk.py
from agents.core.execution_agent import ExecutionAgent
from ai_engine.schemas import Signal
def test_risk_halt(monkeypatch, fake_ex):
    ea = ExecutionAgent(fake_ex, {"bot":{"env":"paper"}})
    rr = ea.risk
    def halt_eval(order): 
        from ai_engine.schemas import RiskDirective
        return RiskDirective(halt=True, reason="daily_stop_loss")
    monkeypatch.setattr(rr, "evaluate_order", halt_eval)
    t = ea.execute_signal(Signal(strategy="trend_following", exchange="kraken", symbol="ETH/USD", side="buy", confidence=0.9, size_quote_usd=20))
    assert t is None
