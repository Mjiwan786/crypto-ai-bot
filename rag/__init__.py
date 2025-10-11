"""
RAG (Retrieval-Augmented Generation) package for crypto AI bot.

Provides LlamaIndex-based RAG functionality for social sentiment and news analysis.
Optional dependency - only loaded when needed.
"""

from .llama_index_client import summarize_trending, analyze_sentiment

__all__ = ["summarize_trending", "analyze_sentiment"]
