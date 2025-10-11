from crypto_ai_bot.config.config_loader import ScalpConfig, load_global_config


def test_load_config_and_validate_allocations(tmp_path):
    # write a temporary YAML file with valid allocations
    yaml_content = """
active_strategies:
  - kraken_scalp
allocations:
  kraken_scalp: 1.0
redis_url: redis://localhost:6379/0
"""
    path = tmp_path / "settings.yaml"
    path.write_text(yaml_content)
    config = load_global_config(str(path))
    assert isinstance(config, ScalpConfig)
    assert config.allocations["kraken_scalp"] == 1.0
    assert abs(sum(config.allocations.values()) - 1.0) < 1e-6


def test_load_config_env_substitution(tmp_path, monkeypatch):
    yaml_content = """
redis_url: ${TEST_REDIS_URL:-redis://localhost:6379/1}
allocations:
  a: 0.5
  b: 0.5
"""
    path = tmp_path / "settings.yaml"
    path.write_text(yaml_content)
    monkeypatch.setenv("TEST_REDIS_URL", "redis://example.com:6379/2")
    cfg = load_global_config(str(path))
    assert cfg.redis_url == "redis://example.com:6379/2"
