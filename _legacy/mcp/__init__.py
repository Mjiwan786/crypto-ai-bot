"""
Model Context Protocol (MCP)
============================

This package defines the interfaces and infrastructure for sharing
contextual information across agents and models.  The MCP acts as a
structured memory layer, allowing agents to access current market
conditions, strategy state and configuration without tightly coupling to
each other.  In a distributed deployment this layer would be backed by
Redis or another fast key‑value store.  For demonstration purposes we
use in‑memory dictionaries.
"""