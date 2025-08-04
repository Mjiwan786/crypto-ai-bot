# Crypto AI Bot

This repository contains a highly modular cryptocurrency trading bot designed
to experiment with a variety of trading strategies.  The architecture is
organised into distinct subsystems for market scanning, signal generation,
execution, risk management, and advanced arbitrage strategies such as
flash loans.  A Redis‑backed context layer allows different agents to
communicate state and adapt to changing market conditions.

## Development

Install Python dependencies with:

```sh
pip install -r requirements.txt
```

To run the test suite:

```sh
pytest
```

## Configuration

Global settings reside in `config/settings.yaml` and per‑agent settings
live in `config/agent_settings.yaml`.  Connection details for Redis
are defined in `mcp/redis_manager.py`.

## Disclaimer

This code is for research and educational purposes only.  Trading
cryptocurrencies involves significant financial risk; use this bot at
your own risk.