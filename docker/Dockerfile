# syntax=docker/dockerfile:1.7
ARG PY_BASE=continuumio/miniconda3:latest
FROM ${PY_BASE}

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=UTC \
    CONDA_DEFAULT_ENV=crypto-bot

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    tini \
    git \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 10001 appuser
WORKDIR /app

# Create conda environment with specific Python version
RUN conda create -n crypto-bot python=3.10.18 -y && \
    conda clean -afy

# Copy requirements first for better caching
COPY requirements*.txt /app/

# Install Python dependencies in conda environment
RUN /opt/conda/envs/crypto-bot/bin/pip install --upgrade pip setuptools wheel && \
    /opt/conda/envs/crypto-bot/bin/pip install -r requirements.txt

# Copy application code
COPY . /app

# Create necessary directories and set permissions
RUN mkdir -p /app/logs /app/data /app/config && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Initialize conda for the user
RUN echo "source /opt/conda/etc/profile.d/conda.sh" >> ~/.bashrc && \
    echo "conda activate crypto-bot" >> ~/.bashrc

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:9000/health || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]
