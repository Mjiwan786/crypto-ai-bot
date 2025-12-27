"""Tool wrappers for orchestrators.

This subpackage contains thin wrappers over your core system components that
expose them as LangChain tools. Each tool should be a lightweight adapter
that imports and calls your own code. Keeping these wrappers separate
means your business logic remains free of LangChain/LangGraph dependencies.

Actual implementations should import your real modules (e.g. signal
analyst, risk manager, execution agent) and return dictionaries or
Pydantic model dumps to maintain structured state across the graph.
"""
