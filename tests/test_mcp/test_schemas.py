import pytest
from pydantic import ValidationError

from mcp.schemas import Signal, Side, Fill, Position, Metric, ContextSnapshot

def test_signal_validation_and_json_roundtrip():
    s = Signal(
        strategy="tf", exchange="binance", symbol="BTC/USDT", 
        side=Side.BUY, confidence=0.9, size_quote_usd=100.0
    )
    data = s.to_json()
    s2 = Signal.from_json(data)
    assert s2.symbol == "BTC/USDT"
    with pytest.raises(ValidationError):
        Signal(
            strategy="tf", exchange="binance", symbol="btcusdt", 
            side=Side.BUY, confidence=1.1, size_quote_usd=-1
        )

def test_fill_and_position():
    f = Fill(price=10.0, qty=2.0, side=Side.SELL, fee=0.0, trade_id="t1")
    assert f.price == 10.0
    p = Position(
        symbol="ETH/USDT", base="ETH", quote="USDT", avg_entry=1000.0, 
        qty=0.5, pnl_unreal=-10.0, leverage=None
    )
    assert p.base == "ETH"

def test_snapshot_and_metric():
    snap = ContextSnapshot(
        env="paper", balances={"USDT": 1000.0}, 
        open_positions=[], last_prices={"BTC/USDT": 100.0}
    )
    assert snap.env == "paper"
    m = Metric(name="orders_total", value=1.0, labels={"env": "paper"})
    assert m.labels["env"] == "paper"
