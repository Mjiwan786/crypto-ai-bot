# Crypto AI Bot Documentation

Welcome to the crypto-ai-bot documentation. This directory contains all technical documentation, specifications, and operational guides for the system.

---

## 📋 Core Documentation

### **[PRD-001: Crypto AI Bot - Core Intelligence Engine](PRD-001-CRYPTO-AI-BOT.md)** 🔴

**This is the authoritative product requirements document.** All development, testing, deployment, and operations must align with PRD-001.

**Contents:**
- Complete functional requirements for all subsystems
- Canonical signal schema (shared across bot, API, UI)
- Data integrity & risk management requirements
- ML transparency & backtesting standards
- Success criteria & measurable KPIs (99.5% uptime, <500ms latency)
- 6-phase implementation roadmap with 48 deliverables

**Audience:** Engineers, Product Managers, Investors, QA, DevOps

---

## 🏗️ Architecture & Design

- **[Architecture Overview](README-ARCH.md)** - System design philosophy, directory layout, component responsibilities
- **[Project Skeleton](PROJECT_SKELETON.md)** - Complete project structure and file organization
- **[Agents Overview](AGENTS_OVERVIEW.md)** - Multi-agent system dataflow, Redis streams, component breakdown

---

## 🔧 Configuration & Setup

- **[Configuration Guide](../CONFIGURATION.md)** - Settings, environment variables, config files
- **[Environment Setup (Windows)](env_setup_windows.md)** - Windows-specific setup instructions
- **[Environment How-To](env_howto.md)** - General environment configuration
- **[Prerequisites (Windows)](prereqs_windows.md)** - System requirements for Windows

---

## 🚀 Deployment & Operations

### Runbooks

- **[RUNBOOK_LIVE.md](../RUNBOOK_LIVE.md)** - Production live trading operations ⚠️ REAL MONEY
- **[RUNBOOK.md](../RUNBOOK.md)** - Publisher runbook for paper trading
- **[Operations Runbook](../OPERATIONS_RUNBOOK.md)** - General operational procedures
- **[Production Deployment](PRODUCTION_DEPLOYMENT.md)** - Production deployment guide
- **[Fly.io Deployment](../FLY_DEPLOYMENT.md)** - Fly.io-specific deployment

### Health & Monitoring

- **[Health Checks](health_checks.md)** - System health monitoring and endpoints
- **[Metrics Monitoring](../RUNBOOK_B1_3_METRICS_MONITORING.md)** - B1.3 metrics and monitoring implementation
- **[Go Live Controls](GO_LIVE_CONTROLS.md)** - Pre-launch validation and controls

---

## 📊 Testing & Quality

- **[Testing & Backtesting Guide](TESTING_AND_BACKTESTING_README.md)** - Comprehensive testing guide
- **[CI Pipeline](CI_PIPELINE.md)** - Continuous integration setup
- **[Parameter Optimization](PARAMETER_OPTIMIZATION.md)** - Strategy parameter tuning

---

## 🛡️ Risk & Safety

- **[Risk Gates](RISK_GATES.md)** - Risk management filters and gates
- **[Regime Gates](REGIME_GATES.md)** - Market regime detection and strategy selection
- **[ATR Risk Model](ATR_RISK_MODEL.md)** - Volatility-based risk adjustment
- **[Liquidity Filters](LIQUIDITY_FILTERS.md)** - Spread and liquidity checks

---

## 📈 Performance & Analytics

- **[PnL Pipeline](PNL_PIPELINE.md)** - Performance tracking and attribution
- **[PnL Monitoring](PNL_MONITORING.md)** - Real-time PnL monitoring
- **[PnL Backfill](PNL_BACKFILL.md)** - Historical PnL data backfilling
- **[PnL Verification](PNL_VERIFICATION.md)** - PnL data validation

---

## 📚 Component-Specific Documentation

### Strategies

- **[Enhanced Scalper README](ENHANCED_SCALPER_README.md)** - High-frequency scalping strategy

### Agents

- **[Agents Overview](AGENTS_OVERVIEW.md)** - Multi-agent architecture and orchestration

---

## 🔄 Deployment Choices

- **[Deploy Choice](deploy_choice.md)** - Deployment platform comparison and recommendations

---

## 📖 How to Use This Documentation

1. **Start with PRD-001** - Understand the authoritative requirements
2. **Read Architecture Docs** - Understand system design and data flow
3. **Follow Setup Guides** - Configure your environment
4. **Use Runbooks** - Operational procedures for deployment and monitoring
5. **Reference Component Docs** - Deep dive into specific subsystems

---

## 🔗 External Resources

- [Main README](../README.md) - Project overview and quickstart
- [Configuration Files](../config/) - YAML configuration files
- [Scripts](../scripts/) - Utility scripts and tools

---

## 📝 Documentation Standards

All documentation in this directory must:
- Be up-to-date with the codebase
- Reference PRD-001 for authoritative requirements
- Use clear, engineering-focused language
- Include code examples where applicable
- Maintain version history

---

**For questions or updates to this documentation, ensure all changes comply with PRD-001.**
