"""
Tests for the configuration loader.

These unit tests verify that YAML files are loaded in the correct
precedence and that environment variables override YAML values.  They
illustrate how to structure tests within the skeleton.
"""
from importlib import reload

import config.loader as loader


def test_yaml_precedence(tmp_path, monkeypatch):
    """Later YAML files should override earlier ones."""
    # Create temporary config directory with two YAML files
    cfg_dir = tmp_path / "config"
    cfg_dir.mkdir()
    (cfg_dir / "settings.yaml").write_text("key: foo\ncommon: base\n")
    (cfg_dir / "agent_settings.yaml").write_text("common: override\n")
    # Temporarily override CONFIG_DIR and _FILES
    monkeypatch.setattr(loader, "CONFIG_DIR", cfg_dir)
    monkeypatch.setattr(loader, "_FILES", ["settings.yaml", "agent_settings.yaml"])
    reload(loader)
    config = loader.get_config()
    assert config["key"] == "foo"
    assert config["common"] == "override"


def test_env_overrides(monkeypatch):
    """Environment variables should override YAML values."""
    monkeypatch.setenv("EXAMPLE_VAR", "env_value")
    # Ensure YAML loader returns something
    monkeypatch.setattr(loader, "_FILES", [])
    reload(loader)
    config = loader.get_config()
    assert config["EXAMPLE_VAR"] == "env_value"
