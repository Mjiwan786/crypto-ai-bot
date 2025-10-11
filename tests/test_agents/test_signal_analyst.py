
def test_signal_analyst():
    from crypto_ai_bot.agents.core.signal_analyst import SignalAnalyst
    sa = SignalAnalyst()
    assert sa.generate_signal({}) == 'hold'
