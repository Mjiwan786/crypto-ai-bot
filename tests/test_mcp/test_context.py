from mcp.redis_client import RedisClient
from mcp.schemas import MarketContext
import os

def test_mcp_context_roundtrip():
    redis = RedisClient()  # Will load REDIS_URL from .env

    test_context = MarketContext(
        sentiment_score=0.68,
        sentiment_trend="bullish",
        regime_state="bull",
        regime_confidence=0.92
    )

    redis.set("mcp:test_context", test_context.model_dump_json())
    raw = redis.get("mcp:test_context")
    restored = MarketContext.parse_raw(raw)

    assert restored.regime_state == "bull"
    assert restored.sentiment_trend == "bullish"
    assert restored.sentiment_score == 0.68
    assert restored.regime_confidence == 0.92

    print("✅ MCP roundtrip success")
    print("📈 Regime:", restored.regime_state)
    print("💬 Sentiment Score:", restored.sentiment_score)
