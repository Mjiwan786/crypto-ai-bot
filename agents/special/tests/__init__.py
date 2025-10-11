"""
Unit tests for special agents - all tests use fakes/mocks only.

These tests verify that special agents:
1. Can be imported safely (no side effects)
2. Can be instantiated safely
3. Detection logic works correctly
4. Do not auto-execute trades
5. Work with fake data only

All tests are hermetic - no network calls, no real APIs.
"""
