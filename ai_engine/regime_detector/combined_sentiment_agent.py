import sys
from pathlib import Path

# Add root directory to sys.path so 'agents' and 'mcp' can be imported
ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

import os
from collections import defaultdict
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from dotenv import load_dotenv

# Load environment variables
load_dotenv(dotenv_path=ROOT_DIR / ".env")

# Try MCP (safe fallback if not enabled during testing)
try:
    from mcp.context import set_context
    MCP_ENABLED = True
except ImportError:
    MCP_ENABLED = False

# Import individual scrapers
from agents.infrastructure.reddit_scraper import fetch_crypto_posts
from agents.infrastructure.news_scraper import fetch_news_articles
from agents.infrastructure.cryptopanic_scraper import get_crypto_news

# VADER analyzer
analyzer = SentimentIntensityAnalyzer()

# Track sentiment per coin
TARGET_COINS = [
    "ETH", "SOL", "ADA", "LINK", "AVAX", "ARB", "OP", "MATIC",
    "AIOZ", "INJ", "SUI", "TIA", "PYTH", "JUP", "BTC"
]

def score_text(text):
    vs = analyzer.polarity_scores(text)
    return vs["compound"]

def extract_sentiments(posts, source):
    scored = []
    for post in posts:
        title = post.get("title", "") or post.get("text", "")
        if not title:
            continue
        score = score_text(title)
        scored.append((title, score, source))
    return scored

def aggregate_scores(all_scores):
    per_coin = defaultdict(list)
    global_scores = []

    for title, score, _ in all_scores:
        matched = False
        for coin in TARGET_COINS:
            if coin in title.upper():
                per_coin[coin].append(score)
                matched = True
        if not matched:
            global_scores.append(score)

    final = {}
    for coin, scores in per_coin.items():
        final[f"sentiment_score_{coin.lower()}"] = round(sum(scores) / len(scores), 3)
    if global_scores:
        final["sentiment_score_overall"] = round(sum(global_scores) / len(global_scores), 3)

    return final

def run_combined_sentiment():
    all_sentiments = []

    # Reddit
    try:
        reddit_posts = fetch_crypto_posts(["CryptoCurrency", "Bitcoin", "ethtrader"], limit=10)
        reddit_titles = [{"title": p["title"]} for p in reddit_posts]
        all_sentiments += extract_sentiments(reddit_titles, "reddit")
    except Exception as e:
        print(f"⚠️ Reddit error: {e}")

    # NewsAPI
    try:
        news = fetch_news_articles(limit=10)
        all_sentiments += extract_sentiments(news, "newsapi")
    except Exception as e:
        print(f"⚠️ NewsAPI error: {e}")

    # Cryptopanic
    try:
        panic = get_crypto_news(limit=10)
        all_sentiments += extract_sentiments(panic, "cryptopanic")
    except Exception as e:
        print(f"⚠️ Cryptopanic error: {e}")

    sentiment_summary = aggregate_scores(all_sentiments)

    if MCP_ENABLED:
        for key, value in sentiment_summary.items():
            set_context(key, value)

    return sentiment_summary

if __name__ == "__main__":
    print("\n🧠 Combined Sentiment Analysis:\n")
    results = run_combined_sentiment()
    for k, v in results.items():
        print(f"{k}: {v}")
