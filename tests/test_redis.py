import redis

r = redis.Redis(
    host='redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com',
    port=19818,
    username='default',
    password='inwjuBWkh4rAtGnbQkLBuPkHXSmfokn8',  # ← replace with your actual password
    decode_responses=True
)

try:
    pong = r.ping()
    print("✅ Connected to Redis Cloud! PING response:", pong)

    r.set("cloud_key", "Hello from Redis Cloud ☁️")
    value = r.get("cloud_key")
    print("🧪 Retrieved value:", value)

except redis.ConnectionError as e:
    print("❌ Redis Cloud connection failed:", e)
