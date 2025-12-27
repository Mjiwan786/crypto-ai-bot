# Deprecated Code

This directory contains legacy code that is no longer actively maintained or used in production.

## Contents

### orchestrator_package/

**Status:** Archived scaffold, not integrated into production

**Description:** AutoGen + LangGraph orchestrator prototype. This was an experimental implementation that provided a stateful pipeline using LangGraph. The production system uses `orchestration/` instead.

**Reason for deprecation:** The production orchestration is handled by `orchestration/master_orchestrator.py` and `orchestration/graph.py`. This package was a proof-of-concept that was never integrated.

**Can be removed:** Yes, after verifying no active code depends on it.

## Usage Policy

- Code in this directory is preserved for reference only
- Do not import from deprecated modules in new code
- These modules may be removed in future cleanup passes

## Active Alternatives

| Deprecated | Active Alternative |
|------------|-------------------|
| `deprecated/orchestrator_package/` | `orchestration/` |
