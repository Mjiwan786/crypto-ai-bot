"""
Tests for the ExecutionAgent.
"""

from __future__ import annotations

from agents.core.execution_agent import ExecutionAgent
from agents.core.signal_analyst import TradingSignal
from config.config_loader import ExchangeSettings, RiskSettings


class DummyGateway:
    """A simple gateway stub for testing execution without hitting real APIs."""

    def __init__(self) -> None:
        self.balance = {"base": 1.0, "quote": 1000.0}
        self.orders = []

    def get_balance(self):
        return self.balance

    def create_order(self, side: str, price: float, amount: float):
        self.orders.append((side, price, amount))
        return "dummy-order-id"


def test_execute_trade(monkeypatch):
    exchange = ExchangeSettings(name="kraken", api_key="", api_secret="")
    risk = RiskSettings(max_drawdown=0.2, position_size=0.5)
    agent = ExecutionAgent(exchange, risk)
    # Replace real gateway with dummy
    dummy = DummyGateway()
    monkeypatch.setattr(agent, "gateway", dummy)
    # Buy signal should use quote balance
    signal = TradingSignal(action="buy", price=10.0, strength=0.1)
    agent.execute_trade(signal)
    assert len(dummy.orders) == 1
    side, price, amount = dummy.orders[0]
    assert side == "buy"
    assert price == 10.0
    # Sell signal should use base balance
    dummy.orders.clear()
    signal = TradingSignal(action="sell", price=20.0, strength=0.1)
    agent.execute_trade(signal)
    assert dummy.orders[0][0] == "sell"