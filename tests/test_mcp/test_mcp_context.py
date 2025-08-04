# tests/test_mcp/test_context.py

from mcp.redis_client import RedisClient
from mcp.schemas import MarketContext

def test_mcp_context_roundtrip():
    redis = RedisClient()

    # Create test context
    test_context = MarketContext(
        sentiment_score=0.68,
        sentiment_trend="bullish",
        regime_state="bull",
        regime_confidence=0.92
    )

    # Save to Redis
    redis.set("mcp:test_context", test_context.model_dump_json())

    # Retrieve and parse
    raw = redis.get("mcp:test_context")
    restored = MarketContext.parse_raw(raw)

    # Print for visibility
    print("✅ MCP roundtrip success")
    print("📈 Regime:", restored.regime_state)
    print("💬 Sentiment Score:", restored.sentiment_score)

if __name__ == "__main__":
    test_mcp_context_roundtrip()
