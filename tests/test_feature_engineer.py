import pandas as pd
from agents.ml.feature_engineer import build_feature_frame, FEATURE_ORDER, SCHEMA_VERSION
from mcp.context import Context

def test_feature_frame_columns_and_nulls():
    ohlcv = pd.DataFrame({
        "open":[1,1,1], "high":[2,2,2], "low":[0.5,0.5,0.5], "close":[1.5,1.4,1.6], "volume":[10,11,12]
    })
    ctx = Context()
    df = build_feature_frame(ctx, ohlcv, {"regime_state":1, "sentiment_score":0.2})
    assert all(c in df.columns for c in FEATURE_ORDER)
    assert "schema_version" in df.columns and int(df["schema_version"].iloc[-1]) == SCHEMA_VERSION
    assert not df.isna().any().any()
    assert list(df.columns) == FEATURE_ORDER
