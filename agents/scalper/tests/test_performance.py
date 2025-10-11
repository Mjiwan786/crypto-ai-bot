from crypto_ai_bot.scalper.monitoring.performance import PerformanceTracker, Trade


def test_performance_tracker_calculations():
    tracker = PerformanceTracker()
    # winning buy trade
    tracker.record_trade(Trade(side="buy", qty=1.0, entry_price=100.0, exit_price=101.0))
    # losing sell trade
    tracker.record_trade(Trade(side="sell", qty=2.0, entry_price=50.0, exit_price=55.0))
    total = tracker.total_pnl()
    # pnl = (101-100)*1 + (50-55)*2 = 1 - 10 = -9
    assert abs(total + 9.0) < 1e-6
    assert tracker.win_rate() == 0.5
    assert abs(tracker.average_trade_return() + 4.5) < 1e-6  # -9/2
