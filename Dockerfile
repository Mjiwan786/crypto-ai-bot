# syntax=docker/dockerfile:1.7
# Two-stage build for crypto-ai-bot
# Stage 1: Build wheels from pyproject.toml
# Stage 2: Runtime with wheel installation

# ===============================================
# Stage 1: Builder - Create wheels
# ===============================================
FROM python:3.10-slim as builder

# Set build environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for building
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libjpeg-dev \
    libpng-dev \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and install build tools
RUN pip install --upgrade pip setuptools wheel build

# Set working directory
WORKDIR /build

# Copy pyproject.toml for wheel building
COPY pyproject.toml ./

# Build wheels from pyproject.toml
RUN python -m build --wheel --outdir /wheels

# ===============================================
# Stage 2: Runtime - Install from wheels
# ===============================================
FROM python:3.10-slim as runtime

# Set runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    TZ=UTC

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    redis-tools \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser -u 10001 -m appuser

# Set working directory
WORKDIR /app

# Copy wheels from builder stage
COPY --from=builder /wheels /wheels

# Install package from wheels
RUN pip install --no-cache-dir --find-links /wheels crypto-ai-bot

# Copy application code
COPY --chown=appuser:appuser agents/ ./agents/
COPY --chown=appuser:appuser ai_engine/ ./ai_engine/
COPY --chown=appuser:appuser base/ ./base/
COPY --chown=appuser:appuser config/ ./config/
COPY --chown=appuser:appuser flash_loan_system/ ./flash_loan_system/
COPY --chown=appuser:appuser mcp/ ./mcp/
COPY --chown=appuser:appuser monitoring/ ./monitoring/
COPY --chown=appuser:appuser orchestration/ ./orchestration/
COPY --chown=appuser:appuser orchestrator_package/ ./orchestrator_package/
COPY --chown=appuser:appuser rag/ ./rag/
COPY --chown=appuser:appuser short_selling/ ./short_selling/
COPY --chown=appuser:appuser strategies/ ./strategies/
COPY --chown=appuser:appuser utils/ ./utils/
COPY --chown=appuser:appuser main.py ./
COPY --chown=appuser:appuser pyproject.toml ./

# Create necessary directories
RUN mkdir -p /app/logs /app/data /app/reports /app/models /app/test_models && \
    chown -R appuser:appuser /app/logs /app/data /app/reports /app/models /app/test_models

# Switch to non-root user
USER appuser

# Health check - ping Redis if REDIS_URL is set
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD if [ -n "$REDIS_URL" ]; then \
        redis-cli -u "$REDIS_URL" --tls --cacert /etc/ssl/certs/ca-certificates.crt ping || exit 1; \
    else \
        redis-cli ping || exit 1; \
    fi

# Default command
CMD ["crypto-ai-bot", "--mode", "paper"]