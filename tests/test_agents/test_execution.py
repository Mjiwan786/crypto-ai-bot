
def test_execution_agent():
    from crypto_ai_bot.agents.core.execution_agent import ExecutionAgent
    agent = ExecutionAgent()
    order_id = agent.place_order('BTC/USD', 'buy', 1.0)
    assert 'BTC/USD' in order_id
