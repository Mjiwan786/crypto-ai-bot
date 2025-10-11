"""
Tests for stream registry functionality.

Comprehensive test coverage for centralized stream name management.
"""

import os
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch

from config.stream_registry import (
    load_streams, 
    get_stream, 
    get_all_streams, 
    assert_no_drift, 
    reset_registry
)
from config.streams_schema import StreamsConfig


class TestStreamRegistry:
    """Test stream registry functionality."""
    
    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()
    
    def test_load_streams_success(self):
        """Test successful loading of streams configuration."""
        config = load_streams()
        
        assert isinstance(config, StreamsConfig)
        assert config.prefix == "kraken"
        assert config.sep == ":"
        assert "trades" in config.publish
        assert "signals" in config.subscribe
    
    def test_get_stream_publish(self):
        """Test getting stream names from publish section."""
        stream_name = get_stream("trades", symbol="XBTUSD")
        assert stream_name == "kraken:trades:XBTUSD"
    
    def test_get_stream_subscribe(self):
        """Test getting stream names from subscribe section."""
        stream_name = get_stream("signals", symbol="XBTUSD")
        assert stream_name == "signals:kraken:XBTUSD"
    
    def test_get_stream_with_multiple_params(self):
        """Test getting stream names with multiple formatting parameters."""
        stream_name = get_stream("ohlcv", timeframe="1m", symbol="XBTUSD")
        assert stream_name == "kraken:ohlc:1m:XBTUSD"
    
    def test_get_stream_missing_key(self):
        """Test error when stream key not found."""
        with pytest.raises(ValueError, match="Stream 'nonexistent' not found"):
            get_stream("nonexistent")
    
    def test_get_stream_missing_format_param(self):
        """Test error when required format parameter is missing."""
        with pytest.raises(ValueError, match="Missing required parameter"):
            get_stream("trades")  # Missing symbol parameter
    
    def test_get_all_streams(self):
        """Test getting all stream patterns."""
        all_streams = get_all_streams()
        
        assert isinstance(all_streams, dict)
        assert "trades" in all_streams
        assert "signals" in all_streams
        assert all_streams["trades"] == "kraken:trades:{symbol}"
    
    def test_caching(self):
        """Test that configuration is cached after first load."""
        config1 = load_streams()
        config2 = load_streams()
        
        # Should be the same instance (cached)
        assert config1 is config2
    
    def test_reset_registry(self):
        """Test that registry can be reset."""
        load_streams()  # Load and cache
        reset_registry()
        
        # Should load fresh instance
        config = load_streams()
        assert isinstance(config, StreamsConfig)


class TestStreamDriftDetection:
    """Test stream drift detection functionality."""
    
    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()
    
    def test_assert_no_drift_clean(self):
        """Test drift detection with clean reference files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a reference file that matches canonical streams
            ref_file = Path(temp_dir) / "test_config.yaml"
            ref_file.write_text("""
streams:
  publish:
    trades: "kraken:trades:XBTUSD"
    orderbook: "kraken:orderbook:ETHUSD"
""")
            
            drift_messages = assert_no_drift([str(ref_file)])
            assert drift_messages == []
    
    def test_assert_no_drift_with_drift(self):
        """Test drift detection with non-canonical streams."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a reference file with non-canonical streams
            ref_file = Path(temp_dir) / "test_config.yaml"
            ref_file.write_text("""
streams:
  publish:
    trades: "kraken:trades:XBTUSD"
    bad_stream: "noncanonical:stream:name"
""")
            
            drift_messages = assert_no_drift([str(ref_file)])
            assert len(drift_messages) > 0
            assert any("Non-canonical stream" in msg for msg in drift_messages)
    
    def test_assert_no_drift_missing_file(self):
        """Test drift detection with missing reference file."""
        drift_messages = assert_no_drift(["nonexistent.yaml"])
        assert len(drift_messages) > 0
        assert any("not found" in msg for msg in drift_messages)
    
    def test_assert_no_drift_multiple_files(self):
        """Test drift detection with multiple reference files."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create clean file
            clean_file = Path(temp_dir) / "clean.yaml"
            clean_file.write_text("""
streams:
  publish:
    trades: "kraken:trades:XBTUSD"
""")
            
            # Create file with drift
            drift_file = Path(temp_dir) / "drift.yaml"
            drift_file.write_text("""
streams:
  publish:
    bad_stream: "noncanonical:stream"
""")
            
            drift_messages = assert_no_drift([str(clean_file), str(drift_file)])
            assert len(drift_messages) > 0
            assert any("Non-canonical stream" in msg for msg in drift_messages)


class TestStreamsSchema:
    """Test Pydantic schema validation."""
    
    def test_valid_config(self):
        """Test valid configuration passes validation."""
        config = StreamsConfig(
            prefix="kraken",
            sep=":",
            publish={"trades": "kraken:trades:{symbol}"},
            subscribe={"signals": "kraken:signals:{symbol}"}
        )
        
        assert config.prefix == "kraken"
        assert config.sep == ":"
        assert config.publish["trades"] == "kraken:trades:{symbol}"
    
    def test_invalid_prefix(self):
        """Test validation fails with incorrect prefix."""
        with pytest.raises(ValueError, match="must start with"):
            StreamsConfig(
                prefix="kraken",
                sep=":",
                publish={"trades": "wrong:trades:{symbol}"},
                subscribe={}
            )
    
    def test_invalid_separator(self):
        """Test validation fails with invalid separator."""
        with pytest.raises(ValueError, match="must be a single character"):
            StreamsConfig(
                prefix="kraken",
                sep="::",  # Invalid: not single character
                publish={"trades": "kraken:trades:{symbol}"},
                subscribe={}
            )
    
    def test_get_all_streams(self):
        """Test getting all streams from config."""
        config = StreamsConfig(
            prefix="kraken",
            sep=":",
            publish={"trades": "kraken:trades:{symbol}"},
            subscribe={"signals": "kraken:signals:{symbol}"}
        )
        
        all_streams = config.get_all_streams()
        assert all_streams == {
            "trades": "kraken:trades:{symbol}",
            "signals": "kraken:signals:{symbol}"
        }
    
    def test_get_stream_patterns(self):
        """Test getting categorized stream patterns."""
        config = StreamsConfig(
            prefix="kraken",
            sep=":",
            publish={"trades": "kraken:trades:{symbol}"},
            subscribe={"signals": "kraken:signals:{symbol}"}
        )
        
        patterns = config.get_stream_patterns()
        assert patterns == {
            "publish.trades": "kraken:trades:{symbol}",
            "subscribe.signals": "kraken:signals:{symbol}"
        }


class TestIntegration:
    """Integration tests for the complete stream registry system."""
    
    def setup_method(self):
        """Reset registry before each test."""
        reset_registry()
    
    def test_end_to_end_workflow(self):
        """Test complete workflow from loading to getting streams."""
        # Load configuration
        config = load_streams()
        assert isinstance(config, StreamsConfig)
        
        # Get various stream names
        trades_stream = get_stream("trades", symbol="XBTUSD")
        assert trades_stream == "kraken:trades:XBTUSD"
        
        signals_stream = get_stream("signals", symbol="ETHUSD")
        assert signals_stream == "signals:kraken:ETHUSD"
        
        ohlcv_stream = get_stream("ohlcv", timeframe="5m", symbol="ADAUSD")
        assert ohlcv_stream == "kraken:ohlc:5m:ADAUSD"
        
        # Get all streams
        all_streams = get_all_streams()
        assert len(all_streams) > 0
        assert "trades" in all_streams
    
    def test_error_handling(self):
        """Test proper error handling for various edge cases."""
        # Test missing stream key
        with pytest.raises(ValueError):
            get_stream("nonexistent")
        
        # Test missing format parameter
        with pytest.raises(ValueError):
            get_stream("trades")  # Missing symbol
        
        # Test invalid format parameter
        with pytest.raises(ValueError):
            get_stream("trades", wrong_param="value")  # Wrong parameter name
