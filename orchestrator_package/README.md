# AutoGen + LangGraph Orchestrator

This archive provides a ready‑to‑use orchestrator for your crypto trading bot
that leverages [AutoGen](https://microsoft.github.io/autogen/) and
[LangGraph](https://github.com/langchain-ai/langgraph) to wrap and sequence
your core business logic. The orchestrator is designed to be added to
an existing codebase without polluting your core modules with
third‑party dependencies.

## Contents

- `orchestrators/tools/`: thin wrappers that expose your signal generator,
  risk manager and execution client as AutoGen tools. The provided
  stubs simply return placeholder values—replace these stubs with
  imports and calls to your own modules.
- `orchestrators/trading_graph.py`: builds a stateful pipeline using
  LangGraph. The pipeline sequentially computes a signal, decides a
  position, runs risk checks and executes a trade.
- `tests/test_orchestrator_smoke.py`: simple tests that ensure the
  orchestrator can run end‑to‑end and that risk limits block oversized
  trades.

## Installation

Install the optional orchestration dependencies in your Python
environment. These packages are not required by your core bot but are
needed to run the orchestrator:

```bash
pip install "autogen-core>=0.7" "autogen-agentchat>=0.7" "langgraph>=0.6" pydantic>=2.7
```

Ensure that your own dependencies (such as your signal analyst, risk
manager and exchange client) are installed separately.

## Usage

You can run the orchestrator graph directly from the command line for
smoke testing or demonstration:

```bash
python -m orchestrators.trading_graph
```

This will execute a mock pipeline using the stub tools and print out the
final state. Replace the stubs in `orchestrators/tools/*.py` with
calls to your real code to integrate the orchestrator with your
application.

### Integrating with Your Application

The orchestrator is packaged separately from your core logic. To wire it
into your application:

1. Replace the stub implementations in `orchestrators/tools/*_tools.py`
   with imports and calls to your own modules. For example, import
   your signal generation function and call it inside `compute_signal`.
2. When using Pydantic models for structured data, call
   `model_dump()` before returning to ensure the graph receives plain
   dictionaries.
3. Import and call `build_graph()` from `orchestrators/trading_graph.py`
   to create a compiled graph. Invoke the graph with an instance of
   `TradeState` to run the pipeline.

You can optionally control whether the orchestrator is used at runtime
via an environment variable. See the conversation context for details
about adding a feature flag in your `main.py`.

## Testing

The provided tests verify that the orchestrator runs to completion
and that risk limits are enforced. Run the test suite with
[pytest](https://docs.pytest.org/en/stable/):

```bash
pip install pytest
pytest -q
```

All tests should pass with the default stubs. As you integrate your own
business logic, keep these tests up to date to ensure that the
orchestrator continues to function correctly.

## License

This orchestration scaffold is provided without warranty. Adapt and use
it in your own projects as needed.
