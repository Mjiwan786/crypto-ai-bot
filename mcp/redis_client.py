import os
import redis
from dotenv import load_dotenv
from pathlib import Path

# ✅ Force load .env from project root
dotenv_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(dotenv_path)

class RedisClient:
    def __init__(self, url=None):
        self.url = url or os.getenv("REDIS_URL")
        print("📡 Redis URL used:", self.url)  # Keep this for now to verify
        if not self.url:
            raise ValueError("Redis URL not provided and not found in .env as REDIS_URL")
        self.client = redis.from_url(self.url, decode_responses=True)

    def ping(self):
        return self.client.ping()

    def set(self, key, value):
        return self.client.set(key, value)

    def get(self, key):
        return self.client.get(key)

    def publish(self, channel, message):
        return self.client.publish(channel, message)

    def subscribe(self, *channels):
        pubsub = self.client.pubsub()
        pubsub.subscribe(*channels)
        return pubsub

    def delete(self, key):
        return self.client.delete(key)
