from unittest.mock import MagicMock, patch
import json

from mcp.schemas import save_schema, load_schema


def test_schema_round_trip():
    """Ensure that schemas can be saved and loaded without loss."""
    sample = {"a": 1, "b": 2}
    key = "test_schema_round_trip"

    # Use a simple in-memory store to avoid requiring a live Redis connection.
    store: dict = {}
    mock_redis = MagicMock()
    mock_redis.set.side_effect = lambda k, v: store.update({k: v})
    mock_redis.get.side_effect = lambda k: store.get(k)

    with patch("mcp.schemas._get_redis_client", return_value=mock_redis):
        save_schema(key, sample)
        loaded = load_schema(key)

    assert loaded == sample