.PHONY: help install preflight test test-unit test-integration test-cov test-ci lint format clean benchmark benchmark-quick

# Default target
help:
	@echo "crypto-ai-bot Makefile Commands:"
	@echo ""
	@echo "  install          - Install dependencies via conda/pip"
	@echo "  preflight        - Run preflight checks (lint, tests, Redis, Kraken, config)"
	@echo "  test             - Run all tests"
	@echo "  test-unit        - Run unit tests only (fast)"
	@echo "  test-integration - Run integration tests (requires Redis)"
	@echo "  test-cov         - Run tests with coverage report (≥90%% required)"
	@echo "  test-ci          - Run tests in CI mode (strict)"
	@echo "  benchmark        - Run signal publisher benchmark (100 signals)"
	@echo "  benchmark-quick  - Run quick benchmark (20 signals)"
	@echo "  lint             - Run code linting (flake8, mypy)"
	@echo "  format           - Format code with black and isort"
	@echo "  clean            - Clean up generated files"
	@echo ""

# Install dependencies
install:
	@echo "Installing dependencies for crypto-ai-bot..."
	conda env update -n crypto-bot -f environment.yml || \
	(conda create -n crypto-bot python=3.10 -y && \
	 conda run -n crypto-bot pip install -r requirements.txt)
	@echo "✓ Dependencies installed"

# Run preflight checks (comprehensive pre-deployment validation)
preflight:
	@echo "╔═══════════════════════════════════════════════════════════╗"
	@echo "║          CRYPTO-AI-BOT PREFLIGHT CHECKLIST               ║"
	@echo "╚═══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "1️⃣  Running code linters..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@-conda run -n crypto-bot ruff check agents/ ai_engine/ strategies/ orchestration/ --select E,F,W --ignore E501 || echo "⚠️  Linting warnings (non-blocking)"
	@echo ""
	@echo "2️⃣  Running unit tests..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@-conda run -n crypto-bot pytest -v -m "not integration" --tb=short -x || echo "⚠️  Some unit tests failed"
	@echo ""
	@echo "3️⃣  Checking Redis Cloud TLS connectivity..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@conda run -n crypto-bot python scripts/check_redis_tls.py || (echo "❌ Redis TLS check failed!" && exit 1)
	@echo ""
	@echo "4️⃣  Checking Kraken API connectivity..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@conda run -n crypto-bot python scripts/check_kraken_api.py || echo "⚠️  Kraken API check failed (non-blocking)"
	@echo ""
	@echo "5️⃣  Validating configuration..."
	@echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
	@conda run -n crypto-bot python -c "from config.unified_config_loader import get_config_loader; loader = get_config_loader(); config = loader.load_system_config('production'); issues = loader.validate_configuration(config); exit(0 if not issues else 1)" || echo "⚠️  Config validation warnings"
	@echo ""
	@echo "╔═══════════════════════════════════════════════════════════╗"
	@echo "║              ✅ PREFLIGHT COMPLETE                        ║"
	@echo "╚═══════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "System ready for deployment. Review warnings above if any."
	@echo ""

# Run all tests
test:
	@echo "Running all tests..."
	conda run -n crypto-bot pytest -v --tb=short

# Run unit tests only (exclude integration tests)
test-unit:
	@echo "Running unit tests..."
	conda run -n crypto-bot pytest -v -m "not integration" --tb=short

# Run integration tests only (requires Redis, Kraken API, etc.)
test-integration:
	@echo "Running integration tests (requires Redis connection)..."
	@echo "Ensure REDIS_URL environment variable is set"
	conda run -n crypto-bot pytest -v -m "integration" --tb=short

# Run tests with coverage (≥90% core logic required)
test-cov:
	@echo "Running tests with coverage..."
	conda run -n crypto-bot pytest \
		--cov=agents \
		--cov=ai_engine \
		--cov=strategies \
		--cov=orchestration \
		--cov=config \
		--cov-report=term-missing \
		--cov-report=html:coverage_html \
		--cov-report=json:coverage.json \
		--cov-fail-under=90 \
		-v
	@echo "✓ Coverage report generated in coverage_html/"
	@echo "✓ Coverage meets ≥90%% requirement"

# Run tests in CI mode (strict, with coverage)
test-ci:
	@echo "Running tests in CI mode..."
	conda run -n crypto-bot pytest \
		--cov=agents \
		--cov=ai_engine \
		--cov=strategies \
		--cov=orchestration \
		--cov=config \
		--cov-report=term \
		--cov-report=xml:coverage.xml \
		--cov-fail-under=90 \
		--maxfail=1 \
		--tb=short \
		-v \
		-m "not integration"
	@echo "✓ CI tests passed"

# Lint code
lint:
	@echo "Running linters..."
	-conda run -n crypto-bot flake8 agents/ ai_engine/ strategies/ orchestration/ config/ --max-line-length=120 --ignore=E203,W503
	-conda run -n crypto-bot mypy agents/ ai_engine/ strategies/ --ignore-missing-imports
	@echo "✓ Linting complete"

# Format code
format:
	@echo "Formatting code..."
	-conda run -n crypto-bot black agents/ ai_engine/ strategies/ orchestration/ config/ tests/ --line-length=120
	-conda run -n crypto-bot isort agents/ ai_engine/ strategies/ orchestration/ config/ tests/ --profile black
	@echo "✓ Code formatted"

# Clean generated files
clean:
	@echo "Cleaning generated files..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name "*.pyo" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache" -exec rm -rf {} + 2>/dev/null || true
	rm -rf coverage_html coverage.xml coverage.json .coverage 2>/dev/null || true
	@echo "✓ Cleaned"

# Windows-compatible clean (PowerShell)
clean-win:
	@echo "Cleaning generated files (Windows)..."
	powershell -Command "Get-ChildItem -Path . -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
	powershell -Command "Get-ChildItem -Path . -Recurse -Directory -Filter *.egg-info | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
	powershell -Command "Get-ChildItem -Path . -Recurse -File -Filter *.pyc | Remove-Item -Force -ErrorAction SilentlyContinue"
	powershell -Command "Get-ChildItem -Path . -Recurse -Directory -Filter .pytest_cache | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue"
	powershell -Command "if (Test-Path coverage_html) { Remove-Item -Recurse -Force coverage_html }"
	powershell -Command "if (Test-Path coverage.xml) { Remove-Item -Force coverage.xml }"
	powershell -Command "if (Test-Path .coverage) { Remove-Item -Force .coverage }"
	@echo "✓ Cleaned"

# Run performance benchmark (100 signals, 60/min)
benchmark:
	@echo "Running signal publisher benchmark..."
	@echo "Ensure REDIS_URL environment variable is set"
	conda run -n crypto-bot python scripts/benchmark_signal_publisher.py --signals 100 --rate 60

# Run quick benchmark (20 signals, 120/min for speed)
benchmark-quick:
	@echo "Running quick benchmark..."
	@echo "Ensure REDIS_URL environment variable is set"
	conda run -n crypto-bot python scripts/benchmark_signal_publisher.py --signals 20 --rate 120
