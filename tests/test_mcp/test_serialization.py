
def test_trade_signal_dataclass():
    from crypto_ai_bot.mcp.schemas import TradeSignal
    ts = TradeSignal(pair='BTC/USD', action='buy', confidence=0.9)
    assert ts.pair == 'BTC/USD'
