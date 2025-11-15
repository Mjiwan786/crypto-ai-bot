"""
Unit tests for Prometheus metrics (E2)

Tests:
- Metrics initialization (enabled/disabled)
- Counter increments
- Gauge updates
- Info metrics
- HTTP server startup (local only)
- Configuration from environment
"""

import pytest
import time
from prometheus_client import CollectorRegistry
from agents.infrastructure.metrics import PrometheusMetrics, get_metrics


class TestPrometheusMetrics:
    """Test Prometheus metrics module"""

    def test_disabled_by_default(self):
        """Metrics are disabled by default for safety"""
        metrics = PrometheusMetrics()

        assert metrics.enabled is False
        assert metrics.get_endpoint() is None

    def test_enable_via_constructor(self):
        """Can enable metrics via constructor"""
        # Use custom registry to avoid port conflicts
        registry = CollectorRegistry()

        metrics = PrometheusMetrics(
            enabled=True,
            port=9091,  # Different port to avoid conflicts
            registry=registry
        )

        assert metrics.enabled is True
        assert metrics.port == 9091

    def test_configuration_from_env(self, monkeypatch):
        """Reads configuration from environment"""
        monkeypatch.setenv('METRICS_ENABLED', 'true')
        monkeypatch.setenv('METRICS_PORT', '9092')
        monkeypatch.setenv('METRICS_HOST', '0.0.0.0')

        registry = CollectorRegistry()
        metrics = PrometheusMetrics(registry=registry)

        assert metrics.enabled is True
        assert metrics.port == 9092
        assert metrics.host == '0.0.0.0'

    def test_localhost_only_by_default(self):
        """Binds to localhost only by default (security)"""
        metrics = PrometheusMetrics()

        assert metrics.host == '127.0.0.1'

    def test_record_publish_when_enabled(self):
        """Records publish events when enabled"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9093, registry=registry)

        # Record some publishes
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('ETH-USD', 'signals:paper')

        # Check counter values
        samples = list(registry.collect())
        published_metric = next(m for m in samples if m.name == 'events_published_total')

        # Find BTC-USD counter
        btc_sample = next(
            s for s in published_metric.samples
            if s.labels.get('pair') == 'BTC-USD' and
               s.labels.get('stream') == 'signals:paper'
        )

        assert btc_sample.value == 2.0

    def test_record_publish_when_disabled(self):
        """Recording publish when disabled is no-op (doesn't crash)"""
        metrics = PrometheusMetrics(enabled=False)

        # Should not raise exception
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('ETH-USD', 'signals:paper')

        # No metrics endpoint
        assert metrics.get_endpoint() is None

    def test_record_error_when_enabled(self):
        """Records error events when enabled"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9094, registry=registry)

        # Record some errors
        metrics.record_error('BTC-USD', 'signals:paper', 'redis_error')
        metrics.record_error('ETH-USD', 'signals:paper', 'timeout')
        metrics.record_error('BTC-USD', 'signals:paper', 'redis_error')

        # Check counter values
        samples = list(registry.collect())
        error_metric = next(m for m in samples if m.name == 'publish_errors_total')

        # Find BTC-USD redis_error counter
        btc_error_sample = next(
            s for s in error_metric.samples
            if s.labels.get('pair') == 'BTC-USD' and
               s.labels.get('error_type') == 'redis_error'
        )

        assert btc_error_sample.value == 2.0

    def test_uptime_tracking(self):
        """Tracks publisher uptime accurately"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9095, registry=registry)

        # Wait a bit
        time.sleep(0.1)

        uptime = metrics.get_uptime()

        # Should be at least 0.1 seconds
        assert uptime >= 0.1
        assert uptime < 1.0  # But not too long

    def test_stream_info_when_enabled(self):
        """Sets stream info when enabled"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9096, registry=registry)

        # Set stream info
        metrics.set_stream_info('signals:paper', mode='paper')

        # Check info metric
        samples = list(registry.collect())
        stream_metric = next(m for m in samples if m.name == 'stream')

        # Info metrics have _info suffix
        info_sample = stream_metric.samples[0]

        assert info_sample.labels.get('stream_name') == 'signals:paper'
        assert info_sample.labels.get('mode') == 'paper'

    def test_multiple_pairs_tracked_separately(self):
        """Different pairs tracked with separate counters"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9097, registry=registry)

        # Record publishes for different pairs
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('ETH-USD', 'signals:paper')
        metrics.record_publish('SOL-USD', 'signals:paper')
        metrics.record_publish('BTC-USD', 'signals:paper')

        # Check counters
        samples = list(registry.collect())
        published_metric = next(m for m in samples if m.name == 'events_published_total')

        # Should have separate samples for each pair
        pair_values = {}
        for sample in published_metric.samples:
            pair = sample.labels.get('pair')
            if pair:
                pair_values[pair] = sample.value

        assert pair_values['BTC-USD'] == 2.0
        assert pair_values['ETH-USD'] == 1.0
        assert pair_values['SOL-USD'] == 1.0

    def test_different_streams_tracked_separately(self):
        """Different streams tracked separately"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9098, registry=registry)

        # Publish to different streams
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('BTC-USD', 'signals:paper:staging')
        metrics.record_publish('BTC-USD', 'signals:live')

        # Check counters
        samples = list(registry.collect())
        published_metric = next(m for m in samples if m.name == 'events_published_total')

        # Should have separate samples for each stream
        stream_values = {}
        for sample in published_metric.samples:
            stream = sample.labels.get('stream')
            if stream and sample.labels.get('pair') == 'BTC-USD':
                stream_values[stream] = sample.value

        assert stream_values['signals:paper'] == 1.0
        assert stream_values['signals:paper:staging'] == 1.0
        assert stream_values['signals:live'] == 1.0

    def test_error_types_tracked_separately(self):
        """Different error types tracked separately"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9099, registry=registry)

        # Record different error types
        metrics.record_error('BTC-USD', 'signals:paper', 'redis_error')
        metrics.record_error('BTC-USD', 'signals:paper', 'timeout')
        metrics.record_error('BTC-USD', 'signals:paper', 'validation_error')
        metrics.record_error('BTC-USD', 'signals:paper', 'redis_error')

        # Check counters
        samples = list(registry.collect())
        error_metric = next(m for m in samples if m.name == 'publish_errors_total')

        # Should have separate samples for each error type
        error_values = {}
        for sample in error_metric.samples:
            error_type = sample.labels.get('error_type')
            if error_type and sample.labels.get('pair') == 'BTC-USD':
                error_values[error_type] = sample.value

        assert error_values['redis_error'] == 2.0
        assert error_values['timeout'] == 1.0
        assert error_values['validation_error'] == 1.0

    def test_get_metrics_singleton(self):
        """get_metrics() returns singleton instance"""
        metrics1 = get_metrics()
        metrics2 = get_metrics()

        assert metrics1 is metrics2

    def test_endpoint_url_format(self):
        """Endpoint URL formatted correctly"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(
            enabled=True,
            port=9100,
            host='127.0.0.1',
            registry=registry
        )

        endpoint = metrics.get_endpoint()

        assert endpoint == 'http://127.0.0.1:9100/metrics'

    def test_disabled_metrics_dont_export(self):
        """Disabled metrics don't start HTTP server"""
        metrics = PrometheusMetrics(enabled=False)

        # Should not have endpoint
        assert metrics.get_endpoint() is None

        # Should still accept calls (no-op)
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_error('BTC-USD', 'signals:paper', 'test')
        metrics.set_stream_info('signals:paper', 'paper')


class TestMetricsIntegration:
    """Integration tests for realistic scenarios"""

    def test_typical_publisher_workflow(self):
        """Metrics work in typical publisher workflow"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9101, registry=registry)

        # Set stream info
        metrics.set_stream_info('signals:paper', mode='paper')

        # Simulate publishing signals
        pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD']

        for pair in pairs:
            # Successful publishes
            for i in range(5):
                metrics.record_publish(pair, 'signals:paper')

            # Some errors
            metrics.record_error(pair, 'signals:paper', 'timeout')

        # Check uptime is tracked
        assert metrics.get_uptime() > 0

        # Check total publishes
        samples = list(registry.collect())
        published_metric = next(m for m in samples if m.name == 'events_published_total')

        total_publishes = sum(s.value for s in published_metric.samples)
        assert total_publishes == 15.0  # 3 pairs * 5 each

    def test_multi_stream_scenario(self):
        """Handles publishing to multiple streams"""
        registry = CollectorRegistry()
        metrics = PrometheusMetrics(enabled=True, port=9102, registry=registry)

        # Publish to different streams
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('BTC-USD', 'signals:paper')
        metrics.record_publish('BTC-USD', 'signals:paper:staging')
        metrics.record_publish('ETH-USD', 'signals:live')

        # Check each stream has separate counts
        samples = list(registry.collect())
        published_metric = next(m for m in samples if m.name == 'events_published_total')

        # Count samples by stream
        stream_counts = {}
        for sample in published_metric.samples:
            stream = sample.labels.get('stream')
            stream_counts[stream] = stream_counts.get(stream, 0) + sample.value

        assert stream_counts['signals:paper'] == 2.0
        assert stream_counts['signals:paper:staging'] == 1.0
        assert stream_counts['signals:live'] == 1.0
