# Scripts Archive

This directory contains superseded scripts that have been archived as part of the scripts consolidation effort (2025-10-13).

## Consolidation Summary

The scripts directory has been streamlined to **8 canonical Python scripts** + minimal platform helpers for production readiness and acquisition preparation.

### Active Canonical Scripts (in scripts/)

1. **preflight.py** - Unified preflight check with 3 modes
   - Consolidated from: `preflight.py`, `preflight_hard_checks.py`, `preflight_comprehensive.py`
   - Modes: `--basic`, `--full`, `--production-grade`
   - Purpose: Environment validation, Redis/Kraken connectivity, system specs

2. **health.py** - System health monitoring
   - Renamed from: `health_check.py`
   - Purpose: Runtime health checks and monitoring

3. **mcp_smoke.py** - MCP server smoke tests
   - Purpose: Model Context Protocol server validation

4. **redis_cloud_smoke.py** - Redis Cloud connectivity tests
   - Purpose: Redis Cloud TLS/SSL validation

5. **backtest.py** - Simple backtesting entry point
   - Purpose: Single entry point for backtesting strategies

6. **start_trading_system.py** - Main trading system launcher
   - Purpose: Comprehensive system startup with all checks

7. **wait_for_redis.py** - Docker/container helper
   - Purpose: Wait for Redis availability before starting services

8. **verify_docker_setup.py** - Container verification
   - Purpose: Docker/Kubernetes deployment validation

### Platform Helpers (in scripts/)

- **__init__.py** - Package initialization
- **setup_conda_environment.py** - Conda environment setup
- **entrypoint.sh** - Container entrypoint (if exists)
- **run_staging.ps1** - Windows staging runner (if exists)

## Archived Scripts

### Preflight Variants (Consolidated into unified preflight.py)

- **preflight_comprehensive.py** - Extensive system checks (1411 lines)
  - Features absorbed: dependency checks, network connectivity, exchange validation, data quality scans
  - Production-grade mode includes these comprehensive checks

- **preflight_hard_checks.py** - Cross-platform deployment checks (807 lines)
  - Features absorbed: host specs, time sync, conda context, secrets hygiene, TLS validation
  - Full and production-grade modes include these checks

### Health Check Variants

- **healthcheck.py** - Duplicate of health_check.py
  - Superseded by: `health.py` (renamed from health_check.py)

### Redis Testing Scripts

- **check_redis_tls.py** - Redis TLS validation
  - Superseded by: `redis_cloud_smoke.py` (more comprehensive)

- **redis_test.py** - Basic Redis testing
  - Superseded by: Redis checks in `preflight.py` and `redis_cloud_smoke.py`

- **test_redis.py** - Redis connection tests
  - Superseded by: `redis_cloud_smoke.py`

- **test_redis_connection.py** - Connection validation
  - Superseded by: `redis_cloud_smoke.py`

### Kraken Testing Scripts

- **kraken_ws_health.py** - Kraken WebSocket health checks
  - Superseded by: WebSocket checks in `preflight.py --production-grade`

- **kraken_ingestor_min.py** - Minimal Kraken data ingestor
  - Superseded by: Main data pipeline in agents/

### Backtest Variants (Consolidated to backtest.py)

All these scripts were experimental or variant implementations that are superseded by the unified `backtest.py` entry point:

- **backtest_all.py** - Run all backtests
- **backtest_enhanced_scalper.py** - Scalper strategy backtest
- **comprehensive_agent_backtest.py** - Agent-based backtesting
- **demo_enhanced_scalper.py** - Scalper demo
- **final_optimized_backtest.py** - Optimized backtest version
- **full_agent_backtest.py** - Full agent backtest
- **leverage_aggressive_backtest.py** - Leveraged strategy test
- **optimized_aggressive_backtest.py** - Aggressive optimization
- **smart_aggressive_backtest.py** - Smart aggressive variant
- **ultimate_aggressive_backtest.py** - Ultimate aggressive variant
- **smoke_backtest.py** - Quick smoke test backtest

**Note:** The canonical `backtest.py` provides a simple, clean entry point. For advanced backtesting, see `backtesting/` directory.

### Test and Smoke Test Scripts

- **run_breakout_smoke.py** - Breakout strategy smoke test (empty file)
- **test_enhanced_integration.py** - Integration tests
- **test_enhanced_scalper.py** - Scalper tests
- **test_feature_engineer_smoke.py** - Feature engineering smoke test
- **test_kraken_ws.py** - Kraken WebSocket tests
- **test_new_strategies.py** - New strategy testing
- **test_staging_setup.py** - Staging setup tests
- **test_strategies_standalone.py** - Standalone strategy tests

**Note:** For comprehensive testing, use `tests/` directory with pytest.

### Runner Scripts (Superseded by start_trading_system.py)

- **run_all_tests_and_backtests.py** - Run all tests and backtests
- **run_data_pipeline.py** - Data pipeline runner
- **run_enhanced_scalper.py** - Enhanced scalper runner
- **run_enhanced_scalper_tests.py** - Scalper test runner
- **run_execution_agent.py** - Execution agent runner
- **run_health_api.py** - Health API runner
- **run_integration_tests.py** - Integration test runner
- **run_mock_data_pipeline.py** - Mock data pipeline
- **run_mock_signal_analyst.py** - Mock signal analyst
- **run_signal_analyst.py** - Signal analyst runner
- **run_staging.py** - Staging environment runner

**Note:** `start_trading_system.py` provides comprehensive orchestration with proper startup sequencing.

### Setup and Utility Scripts

- **sale_prep.py** - Acquisition preparation utility
  - Purpose was to prepare for sale - functionality moved to documentation

- **seed_test_data.py** - Seed test data
  - Superseded by: Test fixtures in `tests/` directory

- **setup_backtest.py** - Backtest setup (empty file)
  - Superseded by: `backtest.py`

- **setup_enhanced_scalper.py** - Scalper setup
  - Superseded by: Configuration-driven setup in `config/`

## Rationale for Consolidation

### Production Readiness

1. **Reduced Surface Area**: 8 scripts instead of 60+ makes the system easier to understand and maintain
2. **Clear Entry Points**: Each script has a single, well-defined purpose
3. **Better Testing**: Fewer scripts mean more focused test coverage
4. **Acquisition Value**: Clean, minimal scripts demonstrate professional engineering

### Maintainability

1. **No Duplication**: Removed duplicate functionality (3 preflight scripts, 2 health checks, 5+ Redis tests)
2. **Unified Logic**: Consolidated checks into single sources of truth
3. **Clear Responsibility**: Each script has a clear, non-overlapping purpose
4. **Better Documentation**: Easier to document and explain 8 scripts vs 60+

### Performance

1. **Faster Checks**: Consolidated preflight with modes (basic/full/production-grade) allows right-sized checks
2. **Less Clutter**: No confusion about which script to run
3. **Better Caching**: Fewer file lookups and imports

## Recovery Instructions

If you need functionality from an archived script:

1. **Check the canonical scripts first**: Most functionality is preserved in the 8 canonical scripts
2. **Review the consolidated script**: For preflight features, check `preflight.py` with different modes
3. **Copy specific functions**: If needed, extract specific functions from archived scripts
4. **Recreate as needed**: Most archived scripts were experimental and can be recreated if truly needed

## Consolidated Features by Script

### preflight.py Modes

- **--basic** (10s): Environment vars, Redis PING/XADD, Kraken REST API
- **--full** (60s): + Python runtime, conda, logs, secrets, config sanity
- **--production-grade** (120s): + Host specs, time sync, WebSocket, detailed reports

All features from the 3 original preflight scripts are available through these modes.

## Questions?

For questions about this consolidation, see:
- `PRD_AGENTIC.md` - Overall architecture
- `BACKTESTING_GUIDE.md` - Backtesting documentation
- `config/CONFIG_USAGE.md` - Configuration guide

---

**Archive Date**: 2025-10-13
**Archived By**: Claude Code consolidation task
**Acquisition Prep**: Yes - preparing for Acquire.com listing
