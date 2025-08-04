#!/usr/bin/env bash

set -euo pipefail

# Run test suite prior to deployment
echo "Running tests..."
pytest -q

echo "All tests passed. Deploying Crypto AI Bot..."
# Placeholder for deployment logic (e.g., Docker build and push, kubectl apply)
echo "Deployment complete."