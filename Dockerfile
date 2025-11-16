# ===============================================
# Crypto AI Bot - Production Docker Image
# Optimized multi-stage build for cloud deployment
# ===============================================

# Stage 1: Build stage
FROM python:3.10-slim AS builder

# Set build environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install build dependencies including TA-Lib
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libffi-dev \
    libssl-dev \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install TA-Lib C library
RUN wget http://prdownloads.sourceforge.net/ta-lib/ta-lib-0.4.0-src.tar.gz && \
    tar -xzf ta-lib-0.4.0-src.tar.gz && \
    cd ta-lib/ && \
    ./configure --prefix=/usr && \
    make && \
    make install && \
    cd .. && \
    rm -rf ta-lib ta-lib-0.4.0-src.tar.gz

# Copy and install Python dependencies
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Stage 2: Production runtime
FROM python:3.10-slim

# Set runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app" \
    TZ=America/Toronto \
    ENVIRONMENT=prod \
    LOG_LEVEL=INFO

WORKDIR /app

# Install runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    redis-tools \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user for security
RUN groupadd -r botuser && useradd -r -g botuser -u 10001 -m botuser

# Copy Python dependencies and TA-Lib libraries from builder stage
COPY --from=builder /usr/local/lib/python3.10/site-packages /usr/local/lib/python3.10/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/lib/libta_lib.* /usr/lib/
COPY --from=builder /usr/include/ta-lib /usr/include/ta-lib

# Copy application code
COPY --chown=botuser:botuser . .

# Create necessary directories with proper permissions
RUN mkdir -p logs data config/certs && \
    chown -R botuser:botuser logs data config

# Ensure Redis CA certificate is present with proper permissions
RUN test -f config/certs/redis_ca.pem && chmod 644 config/certs/redis_ca.pem || echo "Warning: redis_ca.pem not found"

# Switch to non-root user
USER botuser

# Expose health check port
EXPOSE 8080

# Health check using internal health endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command: run the bot with integrated health endpoint and heartbeat
# Use main.py which provides graceful shutdown, health checks, and heartbeat
CMD ["python", "-u", "-m", "main", "run", "--mode", "paper"]
