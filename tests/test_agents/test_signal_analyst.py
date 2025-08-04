from agents.core.signal_analyst import generate_signals


def test_generate_signals_returns_dict():
    result = generate_signals({})
    assert isinstance(result, dict)