"""
Tests for the RAG (LlamaIndex) functionality.

Tests the optional RAG features for sentiment analysis and trending topics.
"""

import pytest
from unittest.mock import patch, Mock
from typing import List, Dict, Any

from rag.llama_index_client import (
    summarize_trending, analyze_sentiment, _basic_summary, _basic_sentiment
)


class TestBasicFunctionality:
    """Test basic RAG functionality when LlamaIndex is not available."""
    
    def test_basic_summary_empty(self):
        """Test basic summary with empty input."""
        result = _basic_summary([])
        assert result == "No content to analyze."
    
    def test_basic_summary_with_content(self):
        """Test basic summary with content."""
        texts = [
            "Bitcoin is showing strong bullish momentum",
            "Ethereum network upgrades are driving positive sentiment",
            "Market volatility concerns are affecting altcoin performance"
        ]
        result = _basic_summary(texts)
        
        assert "Basic analysis" in result
        assert "3 texts" in result
        assert "bitcoin" in result.lower()
        assert "ethereum" in result.lower()
    
    def test_basic_sentiment_empty(self):
        """Test basic sentiment with empty input."""
        result = _basic_sentiment([], "BTC")
        
        assert result["sentiment"] == "neutral"
        assert result["confidence"] == 0.0
        assert result["symbol"] == "BTC"
        assert "No content to analyze" in result["error"]
    
    def test_basic_sentiment_positive(self):
        """Test basic sentiment with positive content."""
        texts = [
            "Bitcoin is mooning!",
            "Bullish momentum continues",
            "Price is pumping up"
        ]
        result = _basic_sentiment(texts, "BTC")
        
        assert result["sentiment"] == "positive"
        assert result["score"] > 0
        assert result["symbol"] == "BTC"
    
    def test_basic_sentiment_negative(self):
        """Test basic sentiment with negative content."""
        texts = [
            "Bitcoin is dumping!",
            "Bearish sentiment prevails",
            "Price is crashing down"
        ]
        result = _basic_sentiment(texts, "BTC")
        
        assert result["sentiment"] == "negative"
        assert result["score"] < 0
        assert result["symbol"] == "BTC"
    
    def test_basic_sentiment_neutral(self):
        """Test basic sentiment with neutral content."""
        texts = [
            "Bitcoin price is stable",
            "Market shows no clear direction",
            "Trading volume is normal"
        ]
        result = _basic_sentiment(texts, "BTC")
        
        assert result["sentiment"] == "neutral"
        assert result["score"] == 0.0
        assert result["symbol"] == "BTC"


class TestLlamaIndexIntegration:
    """Test LlamaIndex integration when available."""
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', True)
    @patch('rag.llama_index_client.VectorStoreIndex')
    @patch('rag.llama_index_client.Document')
    def test_summarize_trending_with_llamaindex(self, mock_document, mock_index_class):
        """Test trending summarization with LlamaIndex."""
        # Mock LlamaIndex components
        mock_doc = Mock()
        mock_document.return_value = mock_doc
        
        mock_index = Mock()
        mock_query_engine = Mock()
        mock_response = Mock()
        mock_response.response = (
            "Bitcoin and Ethereum show strong momentum with positive sentiment."
        )
        mock_query_engine.query.return_value = mock_response
        mock_index.as_query_engine.return_value = mock_query_engine
        mock_index_class.from_documents.return_value = mock_index
        
        texts = [
            "Bitcoin is showing strong bullish momentum",
            "Ethereum network upgrades are driving positive sentiment"
        ]
        
        result = summarize_trending(texts)
        
        assert "Bitcoin and Ethereum show strong momentum" in result
        mock_document.assert_called()
        mock_index_class.from_documents.assert_called()
        mock_query_engine.query.assert_called()
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', True)
    @patch('rag.llama_index_client.VectorStoreIndex')
    @patch('rag.llama_index_client.Document')
    def test_analyze_sentiment_with_llamaindex(self, mock_document, mock_index_class):
        """Test sentiment analysis with LlamaIndex."""
        # Mock LlamaIndex components
        mock_doc = Mock()
        mock_document.return_value = mock_doc
        
        mock_index = Mock()
        mock_query_engine = Mock()
        mock_response = Mock()
        mock_response.response = (
            "Bitcoin shows positive sentiment with bullish momentum and "
            "strong community support."
        )
        mock_query_engine.query.return_value = mock_response
        mock_index.as_query_engine.return_value = mock_query_engine
        mock_index_class.from_documents.return_value = mock_index
        
        texts = [
            "Bitcoin is mooning!",
            "Strong bullish momentum continues"
        ]
        
        result = analyze_sentiment(texts, "BTC")
        
        assert result["sentiment"] == "positive"
        assert result["score"] > 0
        assert result["symbol"] == "BTC"
        assert "Bitcoin shows positive sentiment" in result["analysis"]
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', True)
    @patch('rag.llama_index_client.VectorStoreIndex')
    @patch('rag.llama_index_client.Document')
    def test_analyze_sentiment_general_market(self, mock_document, mock_index_class):
        """Test general market sentiment analysis with LlamaIndex."""
        # Mock LlamaIndex components
        mock_doc = Mock()
        mock_document.return_value = mock_doc
        
        mock_index = Mock()
        mock_query_engine = Mock()
        mock_response = Mock()
        mock_response.response = (
            "Overall cryptocurrency market shows mixed sentiment with some "
            "coins bullish and others bearish."
        )
        mock_query_engine.query.return_value = mock_response
        mock_index.as_query_engine.return_value = mock_query_engine
        mock_index_class.from_documents.return_value = mock_index
        
        texts = [
            "Bitcoin is up, Ethereum is down",
            "Mixed signals in the crypto market"
        ]
        
        result = analyze_sentiment(texts)
        
        assert result["sentiment"] == "neutral"
        assert result["symbol"] is None
        assert "mixed sentiment" in result["analysis"]
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', True)
    @patch('rag.llama_index_client.VectorStoreIndex')
    @patch('rag.llama_index_client.Document')
    def test_llamaindex_error_handling(self, mock_document, mock_index_class):
        """Test error handling when LlamaIndex fails."""
        # Mock LlamaIndex to raise an exception
        mock_index_class.from_documents.side_effect = Exception("LlamaIndex error")
        
        texts = ["Bitcoin is trending"]
        
        # Should fall back to basic functionality
        result = summarize_trending(texts)
        
        assert "Basic analysis" in result
        assert "LlamaIndex not available" in result


class TestFallbackBehavior:
    """Test fallback behavior when LlamaIndex is not available."""
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', False)
    def test_summarize_trending_fallback(self):
        """Test trending summarization fallback."""
        texts = [
            "Bitcoin is showing strong bullish momentum",
            "Ethereum network upgrades are driving positive sentiment"
        ]
        
        result = summarize_trending(texts)
        
        assert "Basic analysis" in result
        assert "LlamaIndex not available" in result
        assert "2 texts" in result
    
    @patch('rag.llama_index_client.LLAMAINDEX_AVAILABLE', False)
    def test_analyze_sentiment_fallback(self):
        """Test sentiment analysis fallback."""
        texts = [
            "Bitcoin is mooning!",
            "Strong bullish momentum continues"
        ]
        
        result = analyze_sentiment(texts, "BTC")
        
        assert result["sentiment"] == "positive"
        assert result["score"] > 0
        assert result["symbol"] == "BTC"
        assert "Basic analysis" in result["analysis"]


if __name__ == "__main__":
    pytest.main([__file__])
