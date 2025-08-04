"""
Special Agents
--------------

This subpackage houses specialised agents that do not fit into the typical
data/decision/action flow.  For instance, an on‑chain data ingestor might
run on a separate schedule and feed metrics into your macro analysis.
"""

__all__ = ["onchain_data_agent"]