# tests/test_agents/test_execution_idempotency.py
from ai_engine.schemas import Signal
from agents.core.execution_agent import ExecutionAgent
import ccxt
class FlakyEx:
    def __init__(self):
        self.calls=0
        self.markets={"ETH/USD":{"precision":{"price":0.1,"amount":0.0001},"limits":{"cost":{"min":5.0}}}}
    def fetch_ticker(self,s): return {"last":2000.0}
    def create_order(self, *a, **k):
        self.calls+=1
        if self.calls==1: raise ccxt.NetworkError("boom")
        return {"id":k["params"]["clientOrderId"],"status":"closed","filled":0.01,"amount":0.01,"average":2000.0}
    def fetch_order(self, *a, **k): return {"status":"closed"}
def test_idempotent(fake_ex=None):
    ea = ExecutionAgent(FlakyEx(), {"bot":{"env":"live"}})
    sig = Signal(strategy="trend_following", exchange="kraken", symbol="ETH/USD", side="buy", confidence=1.0, size_quote_usd=20)
    t = ea.execute_signal(sig)
    assert t and t.id.startswith("cai-")
