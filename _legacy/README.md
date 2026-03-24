# Quarantined Code — Do Not Import

Moved here on 2026-03-24 during engine surgery.
These modules are NOT used by any production Fly.io process.

## What's Here

- `flash_loan_system/` — Flash loan execution optimizer, historical analyzer, opportunity scorer. Future scope, not ready.
- `short_selling/` — Short selling logic. Future scope, not ready.
- `mcp/` — Multi-agent coordination protocol (Redis pub/sub). Replaced by SignalGenerator pipeline.
- `tests/test_execution.py` — Tests for old execution agent (imports from mcp/).
- `tests/test_rsi_bounce_*.py` — Tests for old RSI bounce agent.
- `tests/test_mcp/` — Tests for MCP coordination protocol.

## Revival Guide

- `flash_loan_system/` — useful for future flash loan arbitrage scope
- `short_selling/` — future scope
- `mcp/` — some agents in `agents/core/` still reference `mcp.schemas` and `mcp.redis_manager`; if reviving those agents, also revive this

## To revive: move back, fix imports, add tests, deploy in shadow mode first.
