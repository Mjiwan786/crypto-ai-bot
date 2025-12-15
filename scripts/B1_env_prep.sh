#!/bin/bash
# B1 — Environment Prep & Sanity Check (Bash version)
# For use in Git Bash or WSL on Windows

echo "=== B1 Environment Prep & Sanity Check ==="
echo ""

# Step 1: Verify Python and print version
echo "[1/5] Checking Python version..."
python -V

# Step 2: Install requirements without upgrades
echo ""
echo "[2/5] Installing requirements.txt (no upgrades)..."
python -m pip install --no-upgrade -r requirements.txt

# Step 3: Verify core packages
echo ""
echo "[3/5] Verifying core package availability..."

python << 'EOF'
packages = [
    ("ccxt", "ccxt"),
    ("pandas", "pandas"),
    ("numpy", "numpy"),
    ("ta", "ta")
]

all_ok = True
for name, import_name in packages:
    try:
        mod = __import__(import_name)
        version = getattr(mod, '__version__', 'unknown')
        print(f"✓ {name}: {version}")
    except ImportError:
        print(f"✗ {name}: NOT INSTALLED")
        all_ok = False

# Check TA-Lib (optional)
print("\nChecking TA-Lib availability...")
try:
    import talib
    version = getattr(talib, '__version__', 'unknown')
    print(f"✓ TA-Lib: {version}")
except ImportError:
    print("⚠ TA-Lib: NOT AVAILABLE (will fall back to pure-python indicators)")
EOF

# Step 4: Verify Redis connection
echo ""
echo "[4/5] Testing Redis Cloud connection..."
python << 'EOF'
import redis
try:
    r = redis.from_url(
        'rediss://default:&lt;REDIS_PASSWORD&gt;**%24%24@redis-19818.c9.us-east-1-4.ec2.redns.redis-cloud.com:19818',
        ssl_cert_reqs='required',
        decode_responses=True
    )
    r.ping()
    print('✓ Redis Cloud: CONNECTED')
except Exception as e:
    print(f'✗ Redis Cloud: FAILED - {e}')
EOF

# Step 5: Create reports directory
echo ""
echo "[5/5] Creating /reports directory..."
mkdir -p reports
touch reports/.gitkeep
echo "✓ Created reports directory and .gitkeep"

echo ""
echo "=== Environment Prep Complete ==="
echo "✓ Ready for backtesting (verify output above for any errors)"
