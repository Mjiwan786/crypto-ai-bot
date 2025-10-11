# Project Skeleton

This document provides a comprehensive overview of the crypto-ai-bot project structure, components, and architecture.

## Table of Contents

- [Project Overview](#project-overview)
- [Root Directory Structure](#root-directory-structure)
- [Core Components](#core-components)
- [Configuration System](#configuration-system)
- [Monitoring & Observability](#monitoring--observability)
- [Testing & Quality Assurance](#testing--quality-assurance)
- [Deployment & Operations](#deployment--operations)
- [Development Tools](#development-tools)
- [Data & Models](#data--models)
- [Documentation](#documentation)

## Project Overview

The crypto-ai-bot is a production-ready, multi-agent crypto trading system built with Python 3.10. It features:

- **Multi-Agent Architecture**: AutoGen + LangGraph orchestration
- **Real-Time Data Pipeline**: Redis streams with TLS support
- **Risk Management**: Circuit breakers and position limits
- **Production SLOs**: P95 latency <500ms, 99.5% uptime
- **Comprehensive Monitoring**: Prometheus + Grafana integration

## Root Directory Structure

```
crypto-ai-bot/
├── 📁 agents/                    # Trading agents and strategies
├── 📁 ai_engine/                 # ML and AI components
├── 📁 base/                      # Base classes and interfaces
├── 📁 config/                    # Configuration management
├── 📁 docs/                      # Project documentation
├── 📁 flash_loan_system/         # Flash loan arbitrage
├── 📁 mcp/                       # Message bus and context primitives
├── 📁 monitoring/                # Prometheus metrics and Grafana
├── 📁 orchestration/             # LangGraph orchestration
├── 📁 orchestrator_package/      # Orchestrator components
├── 📁 rag/                       # RAG functionality (LlamaIndex)
├── 📁 reports/                   # Generated reports and analysis
├── 📁 scripts/                   # Utility and deployment scripts
├── 📁 services/                  # Microservices (health API)
├── 📁 short_selling/             # Short selling strategies
├── 📁 strategies/                # Individual trading strategies
├── 📁 tests/                     # Test suite
├── 📁 utils/                     # Utility functions
├── 📄 main.py                    # Main CLI entry point
├── 📄 analyze_trades.py          # Trade analysis tool
├── 📄 ops_mcp.py                 # Operations MCP server
├── 📄 pyproject.toml             # PEP 621 package configuration
├── 📄 requirements*.txt          # Python dependencies
├── 📄 docker-compose.yml         # Docker Compose configuration
├── 📄 Dockerfile                 # Multi-stage Docker build
└── 📄 README.md                  # Project documentation
```

## Core Components

### Agents (`agents/`)
Multi-agent trading system with specialized components:

- **`core/`**: Core agent functionality and base classes
- **`config/`**: Agent-specific configuration management
- **`infrastructure/`**: Infrastructure components (Redis, APIs)
- **`ml/`**: Machine learning components
- **`risk/`**: Risk management and safety systems
- **`scalper/`**: High-frequency scalping strategies
- **`special/`**: Specialized trading agents

### AI Engine (`ai_engine/`)
Machine learning and AI components:

- **`adaptive_learner.py`**: Adaptive learning algorithms
- **`events.py`**: Event handling and processing
- **`flash_loan_advisor.py`**: Flash loan opportunity analysis
- **`global_context.py`**: Global context management
- **`regime_detector/`**: Market regime detection
- **`schemas.py`**: Data schemas and models
- **`signals.py`**: Signal generation and processing
- **`strategy_selector.py`**: Strategy selection algorithms

### Configuration System (`config/`)
Unified configuration management:

- **`agent_config_manager.py`**: Agent configuration management
- **`agent_integration.py`**: Agent integration utilities
- **`agent_settings.yaml`**: Agent-specific settings
- **`base_config.py`**: Base configuration classes
- **`config_loader.py`**: Configuration loading utilities
- **`exchange_configs/`**: Exchange-specific configurations
- **`loader.py`**: Configuration loading system
- **`merge_config.py`**: Configuration merging utilities
- **`optimized_config_loader.py`**: Optimized configuration loading
- **`overrides/`**: Environment-specific overrides
- **`stream_registry.py`**: Stream registration system
- **`streams_schema.py`**: Stream schema definitions
- **`streams.yaml`**: Stream configurations
- **`unified_config_loader.py`**: Unified configuration loading

## Monitoring & Observability

### Monitoring (`monitoring/`)
Comprehensive monitoring and observability:

- **Prometheus metrics**: Performance and health metrics
- **Grafana dashboards**: Visualization and alerting
- **SLO tracking**: Service level objective monitoring
- **Health checks**: System health monitoring
- **Alerting**: Discord and email notifications

### Key Metrics
- **P95 Latency**: <500ms signal processing
- **Uptime**: ≥99.5% availability
- **Stream Lag**: <1s data freshness
- **Duplicate Rate**: <0.1% signal duplication

## Testing & Quality Assurance

### Test Suite (`tests/`)
Comprehensive testing framework:

- **Unit tests**: Individual component testing
- **Integration tests**: Component interaction testing
- **SLO tests**: Performance and latency testing
- **End-to-end tests**: Complete system testing

### Quality Tools
- **Ruff**: Fast Python linter and formatter
- **MyPy**: Static type checking
- **Pytest**: Testing framework
- **Coverage**: Code coverage analysis

## Deployment & Operations

### Docker Configuration
- **`Dockerfile`**: Multi-stage build with wheel installation
- **`docker-compose.yml`**: Service orchestration
- **Health checks**: Container health monitoring
- **TLS support**: Secure Redis Cloud connections

### Environment Management
- **Development**: `env.dev.example`
- **Staging**: `env.staging.example`
- **Production**: `env.prod.example`
- **Local**: `env.local.example`

### CI/CD Pipeline
- **GitHub Actions**: Automated testing and building
- **Python 3.10.18**: Pinned version for stability
- **Quality gates**: Ruff, MyPy, Pytest
- **Security scanning**: Safety and Bandit

## Development Tools

### Scripts (`scripts/`)
Utility and deployment scripts:

- **Test runners**: Enhanced scalper test execution
- **Environment validation**: Configuration validation
- **Data pipeline**: Mock data generation
- **Cleanup utilities**: Repository maintenance

### Code Quality
- **`.editorconfig`**: Editor configuration
- **`.gitignore`**: Git ignore patterns
- **`.gitattributes`**: Git attributes
- **`pyproject.toml`**: PEP 621 package configuration

## Data & Models

### Data Storage
- **Redis streams**: Real-time data pipeline
- **CSV exports**: Trade analysis and reporting
- **Model persistence**: ML model storage

### Models (`models/`, `test_models/`)
- **Trading models**: Strategy-specific models
- **ML models**: Machine learning artifacts
- **Backtest results**: Historical performance data

## Documentation

### Project Documentation
- **`README.md`**: Main project documentation
- **`CHANGELOG.md`**: Version history
- **`SECURITY.md`**: Security policy
- **`CONTRIBUTING.md`**: Contribution guidelines
- **`LICENSE`**: MIT license

### Technical Documentation
- **`docs/`**: Detailed technical documentation
- **Architecture diagrams**: System design
- **API documentation**: Interface specifications
- **Deployment guides**: Setup and configuration

## Key Features

### Multi-Agent Architecture
- **AutoGen**: Agent framework for tool calling
- **LangGraph**: Stateful orchestration and workflows
- **Specialized agents**: Risk, strategy, execution agents

### Real-Time Data Pipeline
- **Redis streams**: High-performance data streaming
- **TLS security**: Encrypted connections
- **Circuit breakers**: Fault tolerance
- **Idempotency**: Data consistency guarantees

### Risk Management
- **Position limits**: Configurable risk controls
- **Drawdown protection**: Loss prevention
- **Emergency stops**: Manual kill switches
- **Circuit breakers**: Automatic risk controls

### Production Readiness
- **SLO compliance**: Performance guarantees
- **Health monitoring**: System health checks
- **Graceful shutdown**: Clean resource cleanup
- **Error handling**: Comprehensive error management

## Getting Started

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd crypto-ai-bot
   ```

2. **Setup environment**
   ```bash
   conda create -n crypto-bot python=3.10
   conda activate crypto-bot
   pip install -e .
   ```

3. **Configure environment**
   ```bash
   cp env.local.example .env.local
   # Edit .env.local with your configuration
   ```

4. **Run tests**
   ```bash
   pytest -q
   ```

5. **Start the system**
   ```bash
   python -m main run --mode paper
   ```

## Architecture Deep Dive

For detailed technical documentation, see:
- [Architecture Overview](README-ARCH.md)
- [Configuration Guide](CONFIGURATION.md)
- [Deployment Guide](DEPLOYMENT.md)
- [API Reference](API.md)

---

*This project skeleton represents a production-ready crypto trading system with enterprise-grade monitoring, risk management, and operational excellence.*
