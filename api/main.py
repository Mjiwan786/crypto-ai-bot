import os
import asyncio
from typing import List, Optional
from fastapi import FastAPI, HTTPException
import redis.asyncio as redis

app = FastAPI()

# Redis connection
redis_client = None

async def get_redis():
    """Get Redis client instance"""
    global redis_client
    if redis_client is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        redis_client = redis.from_url(redis_url, decode_responses=True)
    return redis_client

@app.on_event("startup")
async def startup_event():
    """Initialize Redis connection on startup"""
    await get_redis()

@app.on_event("shutdown")
async def shutdown_event():
    """Close Redis connection on shutdown"""
    global redis_client
    if redis_client:
        await redis_client.close()

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        redis_conn = await get_redis()
        await redis_conn.ping()
        return {"redis": "ok"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Redis connection failed: {str(e)}")

@app.get("/signals/recent")
async def get_recent_signals(limit: int = 200, stream: str = "signals:paper"):
    """Get recent signals from Redis stream"""
    try:
        redis_conn = await get_redis()
        
        # Read from the stream
        messages = await redis_conn.xrevrange(stream, count=limit)
        
        # Format the response
        signals = []
        for message_id, fields in messages:
            signal_data = {
                "id": message_id,
                "data": fields
            }
            signals.append(signal_data)
        
        return {
            "stream": stream,
            "count": len(signals),
            "signals": signals
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch signals: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

