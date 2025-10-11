"""
LlamaIndex RAG client for crypto sentiment and news analysis.

Provides RAG functionality for analyzing social sentiment and news trends.
Optional dependency - only loaded when llama-index-core is installed.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Try to import LlamaIndex, fallback if not available
try:
    from llama_index.core import VectorStoreIndex, Document, Settings
    from llama_index.core.llms import LLM
    from llama_index.core.embeddings import BaseEmbedding
    LLAMAINDEX_AVAILABLE = True
except ImportError:
    LLAMAINDEX_AVAILABLE = False
    VectorStoreIndex = None
    Document = None
    Settings = None
    LLM = Any
    BaseEmbedding = Any


def summarize_trending(texts: List[str]) -> str:
    """
    Summarize trending crypto content using LlamaIndex.
    
    Args:
        texts: List of text content to analyze (news articles, social posts, etc.)
        
    Returns:
        Summary of trending topics and sentiment
    """
    if not LLAMAINDEX_AVAILABLE:
        logger.warning("LlamaIndex not available, returning basic summary")
        return _basic_summary(texts)
    
    try:
        # Create documents from texts
        documents = [Document(text=text) for text in texts if text.strip()]
        
        if not documents:
            return "No content to analyze."
        
        # Create vector store index
        index = VectorStoreIndex.from_documents(documents)
        
        # Create query engine
        query_engine = index.as_query_engine()
        
        # Query for trending analysis
        query = (
            "Which cryptocurrencies show sustained positive momentum and low FUD "
            "in the last 24 hours? Provide tickers, rationale, and sentiment analysis. "
            "Focus on technical indicators and market sentiment trends."
        )
        
        response = query_engine.query(query)
        return str(response.response)
        
    except Exception as e:
        logger.error(f"LlamaIndex summarization failed: {e}")
        return _basic_summary(texts)


def analyze_sentiment(texts: List[str], symbol: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze sentiment for specific crypto symbol or general market.
    
    Args:
        texts: List of text content to analyze
        symbol: Optional crypto symbol to focus on (e.g., "BTC", "ETH")
        
    Returns:
        Dictionary with sentiment analysis results
    """
    if not LLAMAINDEX_AVAILABLE:
        logger.warning("LlamaIndex not available, returning basic sentiment")
        return _basic_sentiment(texts, symbol)
    
    try:
        # Create documents from texts
        documents = [Document(text=text) for text in texts if text.strip()]
        
        if not documents:
            return {
                "sentiment": "neutral",
                "confidence": 0.0,
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": "No content to analyze"
            }
        
        # Create vector store index
        index = VectorStoreIndex.from_documents(documents)
        query_engine = index.as_query_engine()
        
        # Build query based on symbol focus
        if symbol:
            query = (
                f"Analyze the sentiment for {symbol} cryptocurrency. "
                f"Provide sentiment score (-1 to 1), confidence level, "
                f"and key factors driving the sentiment. "
                f"Focus on price action, news, and community sentiment."
            )
        else:
            query = (
                "Analyze overall cryptocurrency market sentiment. "
                "Provide sentiment score (-1 to 1), confidence level, "
                "and key market drivers. Focus on major cryptocurrencies "
                "and market trends."
            )
        
        response = query_engine.query(query)
        
        # Parse response (simplified - in real implementation, you'd use structured output)
        response_text = str(response.response)
        
        # Extract sentiment score (simplified parsing)
        sentiment_score = 0.0
        if "positive" in response_text.lower():
            sentiment_score = 0.5
        elif "negative" in response_text.lower():
            sentiment_score = -0.5
        elif "bullish" in response_text.lower():
            sentiment_score = 0.7
        elif "bearish" in response_text.lower():
            sentiment_score = -0.7
        
        return {
            "sentiment": "positive" if sentiment_score > 0.1 else "negative" if sentiment_score < -0.1 else "neutral",
            "score": sentiment_score,
            "confidence": 0.8,  # Placeholder - would be extracted from response
            "symbol": symbol,
            "analysis": response_text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        
    except Exception as e:
        logger.error(f"LlamaIndex sentiment analysis failed: {e}")
        return _basic_sentiment(texts, symbol)


def _basic_summary(texts: List[str]) -> str:
    """Basic summary when LlamaIndex is not available."""
    if not texts:
        return "No content to analyze."
    
    # Simple keyword extraction and counting
    all_text = " ".join(texts).lower()
    
    # Count mentions of common crypto terms
    crypto_terms = ["bitcoin", "btc", "ethereum", "eth", "crypto", "cryptocurrency", "trading", "price"]
    term_counts = {term: all_text.count(term) for term in crypto_terms}
    
    # Find most mentioned terms
    top_terms = sorted(term_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    
    summary = "Basic analysis (LlamaIndex not available):\n"
    summary += f"Analyzed {len(texts)} texts.\n"
    summary += "Top mentioned terms: " + ", ".join([f"{term}({count})" for term, count in top_terms])
    
    return summary


def _basic_sentiment(texts: List[str], symbol: Optional[str] = None) -> Dict[str, Any]:
    """Basic sentiment analysis when LlamaIndex is not available."""
    if not texts:
        return {
            "sentiment": "neutral",
            "confidence": 0.0,
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "No content to analyze"
        }
    
    all_text = " ".join(texts).lower()
    
    # Simple sentiment analysis based on keywords
    positive_words = ["bullish", "moon", "pump", "rise", "gain", "positive", "good", "up"]
    negative_words = ["bearish", "dump", "crash", "fall", "drop", "negative", "bad", "down"]
    
    positive_count = sum(all_text.count(word) for word in positive_words)
    negative_count = sum(all_text.count(word) for word in negative_words)
    
    if positive_count > negative_count:
        sentiment = "positive"
        score = min(0.5, positive_count / len(texts))
    elif negative_count > positive_count:
        sentiment = "negative"
        score = max(-0.5, -negative_count / len(texts))
    else:
        sentiment = "neutral"
        score = 0.0
    
    return {
        "sentiment": sentiment,
        "score": score,
        "confidence": 0.6,  # Lower confidence for basic analysis
        "symbol": symbol,
        "analysis": f"Basic analysis: {positive_count} positive, {negative_count} negative mentions",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# Example usage
if __name__ == "__main__":
    # Test the RAG functionality
    test_texts = [
        "Bitcoin is showing strong bullish momentum with increased institutional adoption",
        "Ethereum network upgrades are driving positive sentiment in the crypto market",
        "Market volatility concerns are affecting altcoin performance",
        "Regulatory clarity is improving for cryptocurrency trading",
    ]
    
    print("Testing RAG functionality...")
    
    # Test summarization
    summary = summarize_trending(test_texts)
    print(f"Summary: {summary}")
    
    # Test sentiment analysis
    sentiment = analyze_sentiment(test_texts, "BTC")
    print(f"Sentiment: {sentiment}")
    
    # Test general market sentiment
    market_sentiment = analyze_sentiment(test_texts)
    print(f"Market sentiment: {market_sentiment}")
