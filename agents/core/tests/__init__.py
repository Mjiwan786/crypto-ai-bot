"""
Unit tests for agents.core module.

Tests cover:
- Serialization utilities (json_dumps, to_decimal_str, ts_to_iso)
- Redis stream contracts (SignalPayload, MetricsLatencyPayload, HealthStatusPayload)
- Contract validation with Pydantic v2

All tests use fakes/mocks only - no network calls, no external dependencies.
"""
