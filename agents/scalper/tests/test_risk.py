import time

from crypto_ai_bot.config.config_loader import ScalpConfig
from crypto_ai_bot.scalper.execution.position_manager import PositionManager
from crypto_ai_bot.scalper.risk.risk_manager import RiskManager


class DummyConfig(ScalpConfig):
    max_position: float = 1.0
    cooldown_seconds: int = 1


def test_risk_manager_position_limit():
    config = DummyConfig(active_strategies=["kraken_scalp"], allocations={"kraken_scalp": 1.0})
    rm = RiskManager()
    pm = PositionManager()
    # manually set current position near limit
    pm._net_position = 0.9
    allowed = rm.check_risk("buy", 0.2, pm, config)
    assert not allowed


def test_risk_manager_cooldown(monkeypatch):
    config = DummyConfig(active_strategies=["kraken_scalp"], allocations={"kraken_scalp": 1.0})
    config.cooldown_seconds = 2
    rm = RiskManager()
    pm = PositionManager()
    pm._net_position = 0.0
    # first trade allowed
    assert rm.check_risk("buy", 0.5, pm, config)
    # second trade within cooldown should be rejected
    assert not rm.check_risk("buy", 0.1, pm, config)
    # advance time beyond cooldown
    time.sleep(2.1)
    assert rm.check_risk("sell", 0.1, pm, config)
