import os
from collections import defaultdict
from dotenv import load_dotenv
from pathlib import Path
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import requests
from mcp.context import set_context  # ← MCP context injection

# Load .env
load_dotenv(dotenv_path=Path(__file__).resolve().parents[2] / ".env")

API_KEY = os.getenv("CRYPTOPANIC_API_KEY")
analyzer = SentimentIntensityAnalyzer()

# Target coins to track
TARGET_COINS = [
    "ETH", "SOL", "ADA", "LINK", "AVAX", "ARB", "OP", "MATIC",
    "AIOZ", "INJ", "SUI", "TIA", "PYTH", "JUP",
    "BTC"
]

def fetch_news(limit=20):
    if not API_KEY:
        raise ValueError("CRYPTOPANIC_API_KEY not set in .env")

    coins = ",".join(TARGET_COINS)
    url = f"https://cryptopanic.com/api/v1/posts/?auth_token={API_KEY}&filter=hot&currencies={coins}"

    res = requests.get(url)
    res.raise_for_status()
    return res.json().get("results", [])[:limit]

def extract_sentiment(posts):
    sentiment_map = defaultdict(list)

    for post in posts:
        title = post.get("title", "")
        if not title: continue

        score = analyzer.polarity_scores(title)["compound"]

        # Match coin mentions in title to assign score
        for coin in TARGET_COINS:
            if coin in title.upper():
                sentiment_map[coin].append(score)

    # Compute average per-coin sentiment
    return {coin: round(sum(scores)/len(scores), 3)
            for coin, scores in sentiment_map.items() if scores}

def run_sentiment_analysis():
    posts = fetch_news()
    sentiment_scores = extract_sentiment(posts)

    # Inject into MCP context
    for coin, score in sentiment_scores.items():
        context_key = f"sentiment_score_{coin.lower()}"  # e.g., sentiment_score_eth
        set_context(context_key, score)

    return sentiment_scores
