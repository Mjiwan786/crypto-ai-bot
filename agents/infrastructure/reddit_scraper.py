# agents/infrastructure/reddit_scraper.py

import os
import praw
from dotenv import load_dotenv

load_dotenv()

def init_reddit():
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        username=os.getenv("REDDIT_USERNAME"),
        password=os.getenv("REDDIT_PASSWORD"),
        user_agent=os.getenv("REDDIT_USER_AGENT")
    )

def fetch_crypto_posts(subreddits, limit=10):
    reddit = init_reddit()
    results = []

    for sub in subreddits:
        subreddit = reddit.subreddit(sub)
        print(f"\n🔍 Fetching top posts from r/{sub}...")
        for post in subreddit.hot(limit=limit):
            if not post.stickied:
                results.append({
                    "subreddit": sub,
                    "title": post.title,
                    "score": post.score,
                    "created_utc": post.created_utc,
                    "url": post.url
                })
    return results


if __name__ == "__main__":
    subs = ["CryptoCurrency", "Bitcoin", "ethtrader"]
    posts = fetch_crypto_posts(subs, limit=5)

    print("\n✅ Top Reddit Posts:")
    for i, post in enumerate(posts):
        print(f"{i+1}. [{post['subreddit']}] {post['title']} (Score: {post['score']})")
