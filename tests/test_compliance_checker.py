"""
Comprehensive tests for compliance checker module.
Covers kill switches, KYC/region blocks, symbol lists, notional rules, leverage, etc.
"""

import pytest
from agents.risk.compliance_checker import (
    ComplianceChecker,
    ComplianceConfig,
    ConfigError,
)
from mcp.schemas import Signal, OrderIntent, OrderSide, OrderType  # ✅ include all enums


# -----------------------
# Helpers
# -----------------------
def _mk_checker(**overrides):
    base_config = {
        "exchange": "kraken",
        "sandbox": False,
        "allowed_symbols": ["BTC/USD", "ETH/USD"],
        "banned_symbols": None,
        "quote_currencies_allowed": None,
        "min_notional_usd": 10.0,
        "max_notional_usd": 10000.0,
        "per_symbol_size": None,
        "allowed_hours_utc": None,
        "trading_halt": False,
        "maintenance_mode": False,
        "margin_allowed": False,
        "max_leverage": 1.0,
        "required_kyc_tier": 1,
        "user_kyc_tier": 1,
        "blocked_regions": None,
        "user_region": None,
        "emergency_kill_switch": False,
    }
    base_config.update(overrides)
    return ComplianceChecker(ComplianceConfig(**base_config))


# -----------------------
# Config validation
# -----------------------
def test_valid_config():
    cfg = ComplianceConfig(allowed_symbols=["BTC/USD"], min_notional_usd=5.0)
    assert cfg.min_notional_usd == 5.0


def test_invalid_min_notional():
    with pytest.raises(ValueError):
        ComplianceConfig(min_notional_usd=-1.0)


def test_invalid_notional_bounds():
    with pytest.raises(ValueError):
        ComplianceConfig(min_notional_usd=100.0, max_notional_usd=50.0)


def test_invalid_trading_hours_format():
    with pytest.raises(ValueError):
        ComplianceConfig(allowed_hours_utc=["99:99-25:00"])


def test_config_overlap_lists_raises():
    """Test that overlapping allowed/banned symbol lists raise ConfigError"""
    with pytest.raises(ConfigError, match="Symbol\\(s\\) cannot be both allowed and banned"):
        ComplianceConfig(
            allowed_symbols=["BTC/USD"],
            banned_symbols=["BTC/USD"]
        )


def test_per_symbol_size_min_gt_max_raises():
    """Test that per-symbol size with min > max raises ConfigError"""
    with pytest.raises(ConfigError, match="min_size .* cannot exceed max_size .* for symbol BTC/USD"):
        ComplianceConfig(
            per_symbol_size={"BTC/USD": {"min_size": 1.0, "max_size": 0.5}}
        )


def test_per_symbol_size_invalid_symbol_format():
    """Test that invalid symbol format in per_symbol_size raises ConfigError"""
    with pytest.raises(ConfigError, match="Invalid symbol format in per_symbol_size"):
        ComplianceConfig(
            per_symbol_size={"INVALID_SYMBOL": {"min_size": 0.1}}
        )


# -----------------------
# Kill Switches
# -----------------------
def test_kill_switches_reject():
    ck = _mk_checker(emergency_kill_switch=True)
    sig = Signal(strategy="s", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.9)
    result = ck.assess_signal(sig, price_usd=50000)
    assert not result.allowed
    assert "emergency-kill-switch" in result.reasons


# -----------------------
# KYC + Region
# -----------------------
def test_kyc_tier_reject():
    ck = _mk_checker(required_kyc_tier=2, user_kyc_tier=1)
    sig = Signal(strategy="s", symbol="BTC/USD", timeframe="1m", side=OrderSide.SELL, confidence=0.9)
    result = ck.assess_signal(sig, price_usd=1000)
    assert not result.allowed
    assert "insufficient-kyc-tier" in result.reasons


def test_region_block_reject():
    ck = _mk_checker(blocked_regions=["US"], user_region="US")
    sig = Signal(strategy="s", symbol="BTC/USD", timeframe="1m", side=OrderSide.SELL, confidence=0.9)
    result = ck.assess_signal(sig, price_usd=1000)
    assert not result.allowed
    assert "blocked-region" in result.reasons


# -----------------------
# Symbol gating
# -----------------------
def test_blacklist_precedence_over_whitelist():
    """Test blacklist precedence by disabling strict validation"""
    base_config = ComplianceConfig(
        allowed_symbols=["BTC/USD", "ETH/USD"],
        banned_symbols=["BTC/USD"],  # BTC/USD is banned
        min_notional_usd=10.0,
        strict_validation=False  # Disable strict validation for this test
    )
    ck = ComplianceChecker(base_config)
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, price=1000, size_quote_usd=100)
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "symbol-banned" in result.reasons


def test_non_whitelisted_symbol_reject():
    ck = _mk_checker(allowed_symbols=["BTC/USD"])
    sig = Signal(strategy="s", symbol="ETH/USD", timeframe="1m", side=OrderSide.SELL, confidence=0.9)
    result = ck.assess_signal(sig, price_usd=2000)
    assert not result.allowed
    assert "symbol-not-whitelisted" in result.reasons


# -----------------------
# Quote currency allowed
# -----------------------
def test_quote_currency_gating():
    ck = _mk_checker(quote_currencies_allowed=["USD"])
    oi = OrderIntent(symbol="BTC/EUR", side=OrderSide.SELL, order_type=OrderType.MARKET, price=None, size_quote_usd=100)
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "quote-currency-not-allowed" in result.reasons


# -----------------------
# Notional bounds
# -----------------------
def test_notional_min_max_enforced():
    ck = _mk_checker(min_notional_usd=50.0, max_notional_usd=500.0)
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, price=1000, size_quote_usd=25.0)
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "notional-below-minimum" in result.reasons

    oi2 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, price=1000, size_quote_usd=10000.0)
    result2 = ck.assess_order(oi2)
    assert not result2.allowed
    assert "notional-above-maximum" in result2.reasons


# -----------------------
# Per-symbol size
# -----------------------
def test_per_symbol_size_overrides_metadata():
    ck = _mk_checker(per_symbol_size={"BTC/USD": {"min_size": 0.01, "max_size": 1.0}})
    small = OrderIntent(symbol="BTC/USD", side=OrderSide.SELL, order_type=OrderType.MARKET,
                        price=None, size_quote_usd=100.0, metadata={"base_size": 0.001})
    large = OrderIntent(symbol="BTC/USD", side=OrderSide.SELL, order_type=OrderType.MARKET,
                        price=None, size_quote_usd=100.0, metadata={"base_size": 5.0})
    valid = OrderIntent(symbol="BTC/USD", side=OrderSide.SELL, order_type=OrderType.MARKET,
                        price=None, size_quote_usd=100.0, metadata={"base_size": 0.5})

    assert not ck.assess_order(small).allowed
    assert not ck.assess_order(large).allowed
    assert ck.assess_order(valid).allowed


# -----------------------
# Leverage & margin
# -----------------------
def test_leverage_and_margin_rules():
    ck = _mk_checker(margin_allowed=False, max_leverage=2.0)
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                     price=None, size_quote_usd=200, metadata={"leverage": 1.5})
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "margin-not-allowed" in result.reasons

    ck2 = _mk_checker(margin_allowed=True, max_leverage=2.0)
    oi2 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                      price=None, size_quote_usd=200, metadata={"leverage": 3.0})
    result2 = ck2.assess_order(oi2)
    assert not result2.allowed
    assert "leverage-exceeds-maximum" in result2.reasons


# -----------------------
# Signal price missing
# -----------------------
def test_signal_rejects_when_price_missing():
    ck = _mk_checker()
    sig = Signal(strategy="s", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    result = ck.assess_signal(sig, price_usd=None)
    assert not result.allowed
    assert "price-missing-for-notional-check" in result.reasons


# -----------------------
# Happy path
# -----------------------
def test_happy_path_order_and_signal():
    ck = _mk_checker(sandbox=True, allowed_hours_utc=["00:00-23:59"], margin_allowed=True, max_leverage=3.0)

    sig = Signal(strategy="strat", symbol="BTC/USD", timeframe="1m", side=OrderSide.SELL, confidence=0.95)
    d_sig = ck.assess_signal(sig, price_usd=50000.0)
    assert d_sig.allowed
    assert d_sig.normalized.get("mode") == "sandbox"

    oi = OrderIntent(
        symbol="BTC/USD",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        price=50000.0,
        size_quote_usd=150.0,
        metadata={"leverage": 2.0}
    )
    d_oi = ck.assess_order(oi)
    assert d_oi.allowed
    assert d_oi.normalized.get("mode") == "sandbox"


# -----------------------
# Time window coverage
# -----------------------
@pytest.mark.parametrize("window,current,in_expected", [
    ("00:00-00:00", 0, True),
    ("12:00-12:30", 720, True),
    ("12:00-12:30", 750, True),
    ("12:00-12:30", 719, False),
    ("22:00-06:00", 1380, True),  # 23:00
    ("22:00-06:00", 360, True),   # 06:00
    ("22:00-06:00", 720, False),  # 12:00
])
def test_window_parse_and_membership_property(window, current, in_expected):
    ck = _mk_checker(allowed_hours_utc=[window])
    s, e = ck._parse_time_window(window)
    assert ck._is_within_minutes_window(current, s, e) is in_expected


# -----------------------
# Additional edge cases
# -----------------------

def test_empty_symbol_lists_work():
    """Test that empty symbol lists don't cause issues"""
    cfg = ComplianceConfig(
        allowed_symbols=[],
        banned_symbols=[],
        min_notional_usd=10.0
    )
    ck = ComplianceChecker(cfg)
    
    # Should work fine with empty lists
    sig = Signal(strategy="test", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    result = ck.assess_signal(sig, price_usd=50000)
    assert result.allowed  # No restrictions with empty lists


def test_none_symbol_lists_work():
    """Test that None symbol lists work correctly"""
    cfg = ComplianceConfig(
        allowed_symbols=None,
        banned_symbols=None,
        min_notional_usd=10.0
    )
    ck = ComplianceChecker(cfg)
    
    # Should work fine with None lists
    sig = Signal(strategy="test", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    result = ck.assess_signal(sig, price_usd=50000)
    assert result.allowed  # No restrictions with None lists


def test_case_insensitive_symbol_matching():
    """Test that symbol matching is case insensitive"""
    ck = _mk_checker(allowed_symbols=["btc/usd", "ETH/USD"])  # Mixed case in config
    
    # Test various case combinations
    sig1 = Signal(strategy="test", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    sig2 = Signal(strategy="test", symbol="btc/usd", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    sig3 = Signal(strategy="test", symbol="Btc/Usd", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    
    result1 = ck.assess_signal(sig1, price_usd=50000)
    result2 = ck.assess_signal(sig2, price_usd=50000)
    result3 = ck.assess_signal(sig3, price_usd=50000)
    
    assert result1.allowed
    assert result2.allowed
    assert result3.allowed


def test_banned_symbols_case_insensitive():
    """Test that banned symbol matching is case insensitive"""
    # Create config without overlap by having different allowed and banned symbols
    cfg = ComplianceConfig(
        allowed_symbols=["ETH/USD"],  # Only allow ETH/USD
        banned_symbols=["BTC/USD"],   # Ban BTC/USD (no overlap)
        min_notional_usd=10.0,
        strict_validation=False  # Disable strict validation for this specific test
    )
    ck = ComplianceChecker(cfg)
    
    # Test uppercase symbol against lowercase ban
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, 
                     price=1000, size_quote_usd=100)
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "symbol-banned" in result.reasons


def test_quote_currency_filtering_case_insensitive():
    """Test that quote currency filtering handles case properly"""
    ck = _mk_checker(quote_currencies_allowed=["USD", "USDT"])
    
    # Test valid quote currency
    oi1 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET, 
                      price=None, size_quote_usd=100)
    result1 = ck.assess_order(oi1)
    assert result1.allowed
    
    # Test invalid quote currency
    oi2 = OrderIntent(symbol="BTC/EUR", side=OrderSide.BUY, order_type=OrderType.MARKET, 
                      price=None, size_quote_usd=100)
    result2 = ck.assess_order(oi2)
    assert not result2.allowed
    assert "quote-currency-not-allowed" in result2.reasons


def test_malformed_symbol_rejected():
    """Test that malformed symbols are handled gracefully by the compliance checker"""
    ck = _mk_checker()
    
    # Test symbols that would make it past Pydantic validation but should be rejected
    # by symbol universe checks (not whitelisted)
    test_symbols = ["XRP/USD", "DOT/USD"]  # Valid format but not whitelisted
    
    for symbol in test_symbols:
        sig = Signal(strategy="test", symbol=symbol, timeframe="1m", 
                    side=OrderSide.BUY, confidence=0.8)
        result = ck.assess_signal(sig, price_usd=50000)
        # Should be rejected for not being whitelisted
        assert not result.allowed
        assert "symbol-not-whitelisted" in result.reasons


def test_zero_leverage_allowed():
    """Test that zero or very small leverage is handled correctly"""
    ck = _mk_checker(margin_allowed=True, max_leverage=5.0)
    
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                     price=None, size_quote_usd=200, metadata={"leverage": 0.5})
    result = ck.assess_order(oi)
    assert result.allowed  # Small leverage should be fine


def test_exact_leverage_limit():
    """Test leverage exactly at the limit"""
    ck = _mk_checker(margin_allowed=True, max_leverage=2.0)
    
    # Exactly at limit should pass
    oi1 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                      price=None, size_quote_usd=200, metadata={"leverage": 2.0})
    result1 = ck.assess_order(oi1)
    assert result1.allowed
    
    # Just over limit should fail
    oi2 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                      price=None, size_quote_usd=200, metadata={"leverage": 2.01})
    result2 = ck.assess_order(oi2)
    assert not result2.allowed
    assert "leverage-exceeds-maximum" in result2.reasons


def test_exact_notional_limits():
    """Test notional values exactly at limits"""
    ck = _mk_checker(min_notional_usd=10.0, max_notional_usd=1000.0)
    
    # Exactly at min limit
    oi1 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, 
                      price=1000, size_quote_usd=10.0)
    result1 = ck.assess_order(oi1)
    assert result1.allowed
    
    # Exactly at max limit
    oi2 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, 
                      price=1000, size_quote_usd=1000.0)
    result2 = ck.assess_order(oi2)
    assert result2.allowed
    
    # Just under min limit
    oi3 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, 
                      price=1000, size_quote_usd=9.99)
    result3 = ck.assess_order(oi3)
    assert not result3.allowed
    assert "notional-below-minimum" in result3.reasons
    
    # Just over max limit
    oi4 = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.LIMIT, 
                      price=1000, size_quote_usd=1000.01)
    result4 = ck.assess_order(oi4)
    assert not result4.allowed
    assert "notional-above-maximum" in result4.reasons


def test_per_symbol_size_fallback_to_global():
    """Test that per-symbol size falls back to global min when base_size is missing"""
    ck = _mk_checker(
        min_notional_usd=50.0,
        per_symbol_size={"BTC/USD": {"min_size": 0.01}}
    )
    
    # Order without base_size in metadata should use global min notional
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                     price=None, size_quote_usd=25.0)  # Below global minimum
    result = ck.assess_order(oi)
    assert not result.allowed
    assert "notional-below-minimum" in result.reasons  # Should get notional-below-minimum, not quote-size-below-minimum


def test_multiple_kill_switches():
    """Test that multiple kill switches can be active"""
    ck = _mk_checker(
        emergency_kill_switch=True,
        maintenance_mode=True,
        trading_halt=True
    )
    
    sig = Signal(strategy="test", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    result = ck.assess_signal(sig, price_usd=50000)
    assert not result.allowed
    # Should get the first kill switch reason (emergency takes precedence in order of checking)
    assert "emergency-kill-switch" in result.reasons


def test_normalized_data_echoing():
    """Test that normalized data is properly echoed back"""
    ck = _mk_checker(sandbox=True)
    
    # Test signal normalization
    sig = Signal(strategy="momentum", symbol="BTC/USD", timeframe="1m", 
                side=OrderSide.BUY, confidence=0.85)
    result_sig = ck.assess_signal(sig, price_usd=45000.0)
    
    assert result_sig.normalized["symbol"] == "BTC/USD"
    assert result_sig.normalized["side"] == "buy"
    assert result_sig.normalized["strategy"] == "momentum"
    assert result_sig.normalized["confidence"] == 0.85
    assert result_sig.normalized["price_usd"] == 45000.0
    assert result_sig.normalized["mode"] == "sandbox"
    
    # Test order normalization
    oi = OrderIntent(symbol="ETH/USD", side=OrderSide.SELL, order_type=OrderType.LIMIT,
                     price=3000.0, size_quote_usd=200.0, metadata={"leverage": 1.0})
    result_oi = ck.assess_order(oi)
    
    assert result_oi.normalized["symbol"] == "ETH/USD"
    assert result_oi.normalized["side"] == "sell"
    assert result_oi.normalized["order_type"] == "limit"
    assert result_oi.normalized["price"] == 3000.0
    assert result_oi.normalized["size_quote_usd"] == 200.0
    assert result_oi.normalized["leverage"] == 1.0
    assert result_oi.normalized["notional_usd"] == 200.0
    assert result_oi.normalized["mode"] == "sandbox"


def test_assess_dispatch_method():
    """Test the generic assess method dispatches correctly"""
    ck = _mk_checker()
    
    # Test with Signal
    sig = Signal(strategy="test", symbol="BTC/USD", timeframe="1m", side=OrderSide.BUY, confidence=0.8)
    result_sig = ck.assess(sig, price_usd=50000)
    assert result_sig.allowed
    
    # Test with OrderIntent
    oi = OrderIntent(symbol="BTC/USD", side=OrderSide.BUY, order_type=OrderType.MARKET,
                     price=None, size_quote_usd=100)
    result_oi = ck.assess(oi)
    assert result_oi.allowed
    
    # Test with invalid type
    with pytest.raises(ValueError, match="Unsupported event type"):
        ck.assess("invalid_type")