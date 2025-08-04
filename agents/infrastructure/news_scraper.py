import os
import requests
from dotenv import load_dotenv
from pathlib import Path
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Optional: MCP context injection (only needed if integrating)
try:
    from mcp.context import set_context
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

# Load .env from root
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")
API_KEY = os.getenv("NEWSAPI_KEY")

analyzer = SentimentIntensityAnalyzer()

def fetch_news_articles(query="crypto OR bitcoin OR ethereum", limit=10):
    if not API_KEY:
        raise ValueError("🚫 NEWSAPI_KEY not set in .env")

    url = (
        f"https://newsapi.org/v2/everything?"
        f"q={query}&language=en&sortBy=publishedAt&pageSize={limit}&apiKey={API_KEY}"
    )

    res = requests.get(url)
    res.raise_for_status()
    return res.json().get("articles", [])

def analyze_sentiment(title):
    score = analyzer.polarity_scores(title)
    compound = score["compound"]
    label = (
        "positive" if compound > 0.2 else
        "negative" if compound < -0.2 else
        "neutral"
    )
    return label, compound

def run_news_sentiment(limit=10, inject_into_mcp=False):
    articles = fetch_news_articles(limit=limit)
    results = []

    sentiment_scores = []

    for article in articles:
        title = article.get("title", "")
        if not title:
            continue

        label, compound = analyze_sentiment(title)
        sentiment_scores.append(compound)

        results.append({
            "title": title,
            "source": article.get("source", {}).get("name", "Unknown"),
            "url": article.get("url", "#"),
            "published_at": article.get("publishedAt", "Unknown"),
            "sentiment": label,
            "score": compound
        })

    avg_score = round(sum(sentiment_scores) / len(sentiment_scores), 3) if sentiment_scores else 0.0

    if inject_into_mcp and MCP_AVAILABLE:
        set_context("news_sentiment_score", avg_score)

    return results, avg_score

if __name__ == "__main__":
    print("\n📰 Top Crypto News Sentiment (NewsAPI):\n")
    try:
        news, avg = run_news_sentiment(limit=10, inject_into_mcp=False)
        for i, post in enumerate(news):
            print(f"{i+1}. {post['title']}")
            print(f"   ➤ Source: {post['source']}")
            print(f"   ➤ Published: {post['published_at']}")
            print(f"   ➤ Sentiment: {post['sentiment']} ({post['score']:.3f})")
            print(f"   ➤ URL: {post['url']}\n")
        print(f"📊 Average VADER Sentiment Score: {avg:.3f}")
    except Exception as e:
        print(f"❌ Error: {e}")
