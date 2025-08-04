from agents.core.execution_agent import execute_trade


def test_execute_trade_returns_string():
    order_id = execute_trade({})
    assert isinstance(order_id, str)