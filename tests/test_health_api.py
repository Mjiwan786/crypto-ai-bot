"""
Tests for the Health API service.

Tests the FastAPI endpoints for configuration and runtime health monitoring.
"""

import json
from datetime import datetime
from unittest.mock import Mock, patch
from fastapi.testclient import TestClient

import pytest

# Import the app
from services.health_api.app import app

client = TestClient(app)


class MockConfigHealth:
    """Mock ConfigHealth dataclass."""
    def __init__(self):
        self.status = "healthy"
        self.last_update = datetime.utcnow()
        self.version = "1.0.0"
        self.file_exists = True
        self.file_readable = True
        self.syntax_valid = True
        self.validation_errors = []
        self.warnings = []


class MockPerformanceMetrics:
    """Mock PerformanceMetrics dataclass."""
    def __init__(self):
        self.load_times = [0.1, 0.2, 0.15]
        self.validation_times = [0.05, 0.08, 0.06]
        self.cache_hits = 10
        self.cache_misses = 2
        self.memory_usage_mb = 50.0
        self.last_update = datetime.utcnow()
    
    @property
    def avg_load_time(self) -> float:
        return sum(self.load_times) / len(self.load_times)
    
    @property
    def avg_validation_time(self) -> float:
        return sum(self.validation_times) / len(self.validation_times)
    
    @property
    def cache_hit_ratio(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0


class MockConfigManager:
    """Mock ConfigManager."""
    def __init__(self):
        self.health = MockConfigHealth()
        self.current_version = "1.0.0"
    
    def get_config(self):
        return {"test": "config"}


class MockAgentConfigManager:
    """Mock AgentConfigManager."""
    def __init__(self):
        self.metrics = MockPerformanceMetrics()
    
    def get_config(self):
        return {"test": "agent_config"}
    
    def get_performance_metrics(self):
        return self.metrics


@patch('services.health_api.app.ConfigManager')
@patch('services.health_api.app.AgentConfigManager')
def test_healthz_ok(mock_agent_mgr_class, mock_config_mgr_class):
    """Test /healthz endpoint returns ok when managers are available."""
    # Setup mocks
    mock_config_mgr = MockConfigManager()
    mock_agent_mgr = MockAgentConfigManager()
    
    mock_config_mgr_class.get_instance.return_value = mock_config_mgr
    mock_agent_mgr_class.get_instance.return_value = mock_agent_mgr
    
    # Test endpoint
    response = client.get("/healthz")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "ts" in data
    assert data["ts"].endswith("Z")  # UTC timestamp


@patch('services.health_api.app.ConfigManager', None)
@patch('services.health_api.app.AgentConfigManager', None)
def test_healthz_degraded_no_managers():
    """Test /healthz endpoint returns degraded when managers are unavailable."""
    response = client.get("/healthz")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "reason" in data
    assert "ts" in data


@patch('services.health_api.app.ConfigManager')
@patch('services.health_api.app.AgentConfigManager')
def test_healthz_degraded_config_load_fails(mock_agent_mgr_class, mock_config_mgr_class):
    """Test /healthz endpoint returns degraded when config load fails."""
    # Setup mocks
    mock_config_mgr = Mock()
    mock_agent_mgr = MockAgentConfigManager()
    
    # Make config load fail
    mock_config_mgr.get_config.side_effect = Exception("Config load failed")
    
    mock_config_mgr_class.get_instance.return_value = mock_config_mgr
    mock_agent_mgr_class.get_instance.return_value = mock_agent_mgr
    
    # Test endpoint
    response = client.get("/healthz")
    
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert "reason" in data
    assert "Config load failed" in data["reason"]


@patch('services.health_api.app.ConfigManager')
@patch('services.health_api.app.AgentConfigManager')
def test_config_health_success(mock_agent_mgr_class, mock_config_mgr_class):
    """Test /config/health endpoint returns merged health data."""
    # Setup mocks
    mock_config_mgr = MockConfigManager()
    mock_agent_mgr = MockAgentConfigManager()
    
    mock_config_mgr_class.get_instance.return_value = mock_config_mgr
    mock_agent_mgr_class.get_instance.return_value = mock_agent_mgr
    
    # Test endpoint
    response = client.get("/config/health")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check required keys
    assert "main" in data
    assert "agent" in data
    assert "version" in data
    assert "updated_at" in data
    
    # Check main config health structure
    main_health = data["main"]
    assert "status" in main_health
    assert "last_update" in main_health
    assert "version" in main_health
    
    # Check agent metrics structure
    agent_health = data["agent"]
    assert "avg_load_time" in agent_health
    assert "avg_validation_time" in agent_health
    assert "cache_hit_ratio" in agent_health
    assert "cache_hits" in agent_health
    assert "cache_misses" in agent_health
    assert "last_update" in agent_health
    
    # Check timestamp format
    assert data["updated_at"].endswith("Z")


@patch('services.health_api.app.ConfigManager', None)
def test_config_health_no_config_manager():
    """Test /config/health endpoint returns 503 when ConfigManager unavailable."""
    response = client.get("/config/health")
    
    assert response.status_code == 503
    data = response.json()
    assert "ConfigManager unavailable" in data["detail"]


@patch('services.health_api.app.ConfigManager')
@patch('services.health_api.app.AgentConfigManager', None)
def test_config_health_no_agent_manager(mock_config_mgr_class):
    """Test /config/health endpoint returns 503 when AgentConfigManager unavailable."""
    mock_config_mgr = MockConfigManager()
    mock_config_mgr_class.get_instance.return_value = mock_config_mgr
    
    response = client.get("/config/health")
    
    assert response.status_code == 503
    data = response.json()
    assert "AgentConfigManager unavailable" in data["detail"]


@patch('services.health_api.app.ConfigManager')
@patch('services.health_api.app.AgentConfigManager')
def test_config_perf_success(mock_agent_mgr_class, mock_config_mgr_class):
    """Test /config/perf endpoint returns separated performance data."""
    # Setup mocks
    mock_config_mgr = MockConfigManager()
    mock_agent_mgr = MockAgentConfigManager()
    
    mock_config_mgr_class.get_instance.return_value = mock_config_mgr
    mock_agent_mgr_class.get_instance.return_value = mock_agent_mgr
    
    # Test endpoint
    response = client.get("/config/perf")
    
    assert response.status_code == 200
    data = response.json()
    
    # Check required keys
    assert "main" in data
    assert "agent" in data
    
    # Check main config health structure
    main_health = data["main"]
    assert "status" in main_health
    assert "last_update" in main_health
    
    # Check agent performance structure
    agent_perf = data["agent"]
    assert "load_times" in agent_perf
    assert "validation_times" in agent_perf
    assert "cache_hits" in agent_perf
    assert "cache_misses" in agent_perf


@patch('services.health_api.app.ConfigManager', None)
def test_config_perf_no_config_manager():
    """Test /config/perf endpoint returns 503 when ConfigManager unavailable."""
    response = client.get("/config/perf")
    
    assert response.status_code == 503
    data = response.json()
    assert "ConfigManager unavailable" in data["detail"]


def test_safe_dump_dataclass():
    """Test safe_dump function with dataclass."""
    from services.health_api.app import safe_dump
    
    # Test with mock dataclass
    mock_health = MockConfigHealth()
    result = safe_dump(mock_health)
    
    assert isinstance(result, dict)
    assert "status" in result
    assert "version" in result


def test_safe_dump_pydantic():
    """Test safe_dump function with Pydantic model."""
    from services.health_api.app import safe_dump
    
    # Create a simple Pydantic-like object with model_dump
    class MockPydantic:
        def model_dump(self):
            return {"test": "value", "nested": {"key": "val"}}
    
    mock_obj = MockPydantic()
    result = safe_dump(mock_obj)
    
    assert isinstance(result, dict)
    assert result["test"] == "value"
    assert result["nested"]["key"] == "val"


def test_safe_dump_fallback():
    """Test safe_dump function fallback behavior."""
    from services.health_api.app import safe_dump
    
    # Test with regular dict
    regular_dict = {"test": "value"}
    result = safe_dump(regular_dict)
    
    assert isinstance(result, dict)
    assert result["test"] == "value"
