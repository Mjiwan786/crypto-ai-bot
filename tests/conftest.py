# tests/conftest.py
import pytest
class FakeExchange:
    def __init__(self):
        self.markets = {"ETH/USD": {"precision":{"price":0.1,"amount":0.0001},
                                    "limits":{"cost":{"min":5.0}}}}
    def fetch_ticker(self, symbol): return {"last": 2000.0}
    def create_order(self, symbol, type_, side, amount, price=None, params=None):
        return {"id": params.get("clientOrderId","x"), "status":"closed","filled":amount,"amount":amount,"average":2000.0}
    def fetch_order(self, oid, symbol): return {"id":oid, "status":"closed","filled":1.0,"average":2000.0}

@pytest.fixture
def fake_ex(): return FakeExchange()
