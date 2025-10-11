#!/usr/bin/env bash
set -euo pipefail

# Initialize conda
source /opt/conda/etc/profile.d/conda.sh

# Activate crypto-bot environment
conda activate crypto-bot

echo "[entrypoint] Environment: ${ENVIRONMENT:-unset}"
echo "[entrypoint] Python: $(python --version)"
echo "[entrypoint] Conda env: $CONDA_DEFAULT_ENV"

if [ -f "scripts/preflight.py" ]; then
  echo "[entrypoint] Running preflight..."
  python scripts/preflight.py --verbose || { echo "[entrypoint] Preflight failed"; exit 1; }
fi

# Start the bot (prefer module if available)
if python -c "import importlib.util,sys; sys.exit(0 if importlib.util.find_spec('main') else 1)"; then
  python -m main || python main.py
else
  # fallback to a known entry if your repo uses something else
  python main.py || python app.py
fi
