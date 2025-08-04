from mcp.schemas import save_schema, load_schema


def test_schema_round_trip():
    """Ensure that schemas can be saved and loaded without loss."""
    sample = {"a": 1, "b": 2}
    key = "test_schema_round_trip"
    save_schema(key, sample)
    loaded = load_schema(key)
    assert loaded == sample