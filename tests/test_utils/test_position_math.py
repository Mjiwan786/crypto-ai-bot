# tests/test_utils/test_position_math.py
from utils.position_math import round_price, enforce_min_notional
def test_round_and_min_notional():
    assert round_price(2000.07, 0.1) == 2000.0
    amt, ok = enforce_min_notional(0.002, 2000.0, 5.0, 0.0001)  # 0.002*2000 = $4 < $5
    assert ok and amt > 0.002
