# Architecture Overview

> **📋 For authoritative requirements and specifications, see [PRD-001: Crypto AI Bot - Core Intelligence Engine](PRD-001-CRYPTO-AI-BOT.md)**

This document provides a high‑level overview of the recommended architecture for a crypto trading bot. The goal is to separate concerns cleanly, making it easier to extend, test and maintain your code.

All architectural decisions must align with the requirements defined in **PRD-001**, which serves as the single source of truth for this repository.

## Directory layout

The skeleton uses a flat top‑level package structure.  Each directory under the project root has a specific purpose and can be independently owned and tested.

| Directory              | Responsibility                                                                                                                                      |
|------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| **config/**            | Contains all YAML configuration files.  A single loader (`config/loader.py`) merges these files and environment variables into a unified config.     |
| **agents/**            | Hosts high‑level trading agents that orchestrate strategies, risk management and execution logic.  Agents consume signals from the strategy modules. |
| **ai_engine/**         | Houses machine learning or reinforcement learning components that adapt strategies, select regimes or otherwise enhance trading decisions.            |
| **strategies/**        | Contains individual strategy implementations (e.g. momentum, mean reversion).  Each should subclass a base strategy defined in `base/strategy.py`.   |
| **base/**              | Defines abstract base classes and interfaces common to strategies, agents and other components.  Implementations should depend on these interfaces.  |
| **flash_loan_system/** | Modules related to executing flash loan arbitrage opportunities, including opportunity identification, scoring and execution.                        |
| **mcp/**               | Message bus and context primitives built on top of Redis (or another message broker).  Used for passing messages between agents and external systems.|
| **monitoring/**        | Contains exporters, Prometheus metrics definitions and Grafana dashboards.  Keeping monitoring logic separate makes it easy to enable/disable it.     |
| **orchestrators/**     | Scripts that wire together agents and strategies into a running system.  Use these to assemble multi‑agent systems or special execution flows.        |
| **short_selling/**     | Modules for short selling, borrowing and lending mechanics.                                                                                         |
| **utils/**             | Exchange‑agnostic helper functions such as logging, retry logic, or mathematics.                                                                     |
| **scripts/**           | Entry points for backtests, preflight checks, deployment or other maintenance tasks.                                                                |
| **tests/**             | Unit and integration tests.  Structure the test tree to mirror the code tree.  For example, tests for `agents/scalper` live under `tests/agents`.    |
| **docs/**              | Project documentation.  Add architecture diagrams, developer guides, API docs and other materials here.                                             |

## Configuration merging

The skeleton enforces a single source of truth for configuration.  All YAML files live in the `config/` folder and are loaded by `config/loader.py`.  The loader merges these files with environment variables in the following order of precedence:

1. `settings.yaml` – global default values.
2. `agent_settings.yaml` – overrides for your trading agent(s).
3. `scalping_settings.yaml` – overrides specific to scalping strategies (or any other strategy‑specific file you add).
4. Environment variables – final overrides for any key.

You can extend this order by adding more YAML files and passing them to the `get_config()` function; just update the list of files in the loader.

## Continuous integration

A GitHub Actions workflow is included under `.github/workflows/ci.yml`.  It runs on every push and pull request, performing the following steps:

* Checks out the repository.
* Sets up a Python matrix (3.10 and 3.11 by default).
* Installs dependencies from `requirements.txt` (or from `pyproject.toml` if you add dependencies there).
* Runs [Ruff](https://beta.ruff.rs/docs/) for fast linting.
* Runs [mypy](https://mypy-lang.org/) for static type checking.
* Executes your unit tests with [pytest](https://docs.pytest.org/).

You can customise the workflow to include additional checks (e.g. formatting with Black, uploading backtest artefacts as build artifacts, scanning secrets with Gitleaks).

## Testing guidelines

* Mirror your test modules to your code modules.  For example, tests for `agents/scalper/engine.py` should live in `tests/agents/scalper/test_engine.py`.
* Keep unit tests fast; use mocks for network calls and external dependencies.  Only write integration tests when necessary.
* Run tests frequently as you develop.  Running `pytest -q` should always pass before merging changes.

## Extending this skeleton

This skeleton provides the scaffolding only.  You need to fill in the actual trading logic (strategies, agents, order execution, risk controls) yourself.  When adding new modules:

* Place them in the appropriate directory with an `__init__.py` file.
* Add corresponding tests under `tests/`.
* Update `pyproject.toml` or `requirements.txt` with any new dependencies.
* Document your module in `docs/`.
