def test_public_api_surface():
    import mcp
    # spot check key symbols exist
    for name in [
        "OrderSide","OrderType","TimeInForce",
        "VersionedBaseModel",
        "Signal","OrderIntent","PolicyUpdate","MetricsTick",
        "export_json_schema",
        "RedisManager","MCPContext",
        "MCPError","RedisUnavailable","SerializationError","CircuitOpenError",
        "BOT_ENV","ns_key","channel","stream",
    ]:
        assert hasattr(mcp, name), f"missing {name} in mcp public API"
