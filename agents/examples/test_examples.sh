#!/bin/bash
# Quick test runner for examples
# Usage: bash agents/examples/test_examples.sh

echo "=================================="
echo "Testing Crypto AI Bot Examples"
echo "=================================="
echo ""

# Activate conda environment
echo "1. Activating conda environment..."
eval "$(conda shell.bash hook)"
conda activate crypto-bot
echo "✅ Environment activated"
echo ""

# Test 1: Generate sample CSV
echo "2. Testing CSV generation..."
python -m agents.examples.generate_sample_csv --output test_data.csv --bars 100
if [ $? -eq 0 ]; then
    echo "✅ CSV generation works"
else
    echo "❌ CSV generation failed"
    exit 1
fi
echo ""

# Test 2: Backtest with generated data
echo "3. Testing backtest with generated data..."
python -m agents.examples.backtest_one_pair --generate-data --bars 200 --output test_backtest.png
if [ $? -eq 0 ]; then
    echo "✅ Backtest works"
else
    echo "❌ Backtest failed"
    exit 1
fi
echo ""

# Test 3: Scan and publish (short duration for testing)
echo "4. Testing scan and publish (10 second test)..."
if [ -z "$REDIS_URL" ]; then
    echo "⚠️  REDIS_URL not set, skipping Redis test"
    echo "   Set REDIS_URL in .env to test Redis functionality"
else
    timeout 10 python -m agents.examples.scan_and_publish --duration 10 --interval 1
    if [ $? -eq 124 ] || [ $? -eq 0 ]; then
        echo "✅ Scan and publish works"
    else
        echo "❌ Scan and publish failed"
        exit 1
    fi
fi
echo ""

# Cleanup
echo "5. Cleaning up test files..."
rm -f test_data.csv test_backtest.png
echo "✅ Cleanup complete"
echo ""

echo "=================================="
echo "All Tests Passed! ✅"
echo "=================================="
echo ""
echo "Examples are ready to use:"
echo "  - scan_and_publish.py"
echo "  - backtest_one_pair.py"
echo "  - generate_sample_csv.py"
echo ""
