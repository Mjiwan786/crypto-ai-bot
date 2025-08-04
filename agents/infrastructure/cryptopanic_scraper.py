import os
import requests
from dotenv import load_dotenv
from pathlib import Path
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

# Load .env from project root
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

# Initialize VADER sentiment analyzer
analyzer = SentimentIntensityAnalyzer()

# Load API key from env
API_KEY = os.getenv("CRYPTOPANIC_API_KEY")

# List of target coins (major + emerging altcoins)
TARGET_COINS = [
    "ETH", "SOL", "ADA", "LINK", "AVAX", "ARB", "OP", "MATIC",
    "AIOZ", "INJ", "SUI", "TIA", "PYTH", "JUP",
    "BTC"
]

def get_crypto_news(limit=10, sentiment_filter=None):
    """Fetch hot crypto news from Cryptopanic API."""
    if not API_KEY:
        raise ValueError("🚫 CRYPTOPANIC_API_KEY not set in .env!")

    currencies_param = ",".join(TARGET_COINS)
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={API_KEY}&filter=hot&currencies={currencies_param}"

    if sentiment_filter:
        url += f"&sentiment={sentiment_filter}"  # Optional: "positive" or "negative"

    res = requests.get(url)
    res.raise_for_status()
    return res.json().get("results", [])[:limit]

def classify_sentiment(text):
    """Run VADER sentiment analysis on title."""
    score = analyzer.polarity_scores(text)
    compound = score["compound"]
    sentiment = (
        "positive" if compound > 0.2 else
        "negative" if compound < -0.2 else
        "neutral"
    )
    return sentiment, compound

if __name__ == "__main__":
    print("\n🔍 Top Altcoin News from Cryptopanic:\n")
    try:
        posts = get_crypto_news(limit=10)

        for i, post in enumerate(posts):
            title = post.get("title", "No title")
            source = post.get("source", {}).get("title", "Unknown")
            published = post.get("published_at", "Unknown")
            url = post.get("url", "#")

            # VADER sentiment classification
            sentiment, compound = classify_sentiment(title)

            print(f"{i+1}. {title}")
            print(f"   ➤ Source: {source}")
            print(f"   ➤ Published: {published}")
            print(f"   ➤ URL: {url}")
            print(f"   ➤ VADER Sentiment: {sentiment} ({compound:.3f})\n")

    except Exception as e:
        print(f"❌ Error fetching news: {e}")
