import os
from dotenv import load_dotenv
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
import requests
import praw
import tweepy

load_dotenv()

class SentimentAgent:
    def __init__(self):
        self.analyzer = SentimentIntensityAnalyzer()

        # Twitter setup
        self.twitter_client = tweepy.Client(
            bearer_token=os.getenv("TWITTER_BEARER_TOKEN")
        )

        # Reddit setup
        self.reddit = praw.Reddit(
            client_id=os.getenv("REDDIT_CLIENT_ID"),
            client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
            user_agent=os.getenv("REDDIT_USER_AGENT")
        )

        # News source (mock or use Cryptopanic if needed)
        self.news_api_key = os.getenv("NEWS_API_KEY")  # optional

    def analyze(self, symbol: str) -> str:
        twitter_score = self._analyze_twitter(symbol)
        reddit_score = self._analyze_reddit(symbol)
        news_score = self._analyze_news(symbol)

        scores = [twitter_score, reddit_score, news_score]
        scores = [s for s in scores if s is not None]

        if not scores:
            return f"Sentiment for {symbol} is unknown (no data)."

        avg_score = sum(scores) / len(scores)
        sentiment = self._interpret_score(avg_score)
        return f"Sentiment for {symbol}: {sentiment} ({avg_score:.2f}) based on Twitter, Reddit, and News."

    def _analyze_twitter(self, symbol: str):
        try:
            query = f"{symbol} crypto lang:en -is:retweet"
            tweets = self.twitter_client.search_recent_tweets(query=query, max_results=20).data
            if not tweets:
                return None
            sentiments = [self.analyzer.polarity_scores(t.text)["compound"] for t in tweets]
            return sum(sentiments) / len(sentiments)
        except Exception as e:
            print(f"[Twitter Error] {e}")
            return None

    def _analyze_reddit(self, symbol: str):
        try:
            subreddit = self.reddit.subreddit("CryptoCurrency")
            posts = subreddit.search(symbol, limit=20)
            sentiments = [self.analyzer.polarity_scores(post.title)["compound"] for post in posts]
            return sum(sentiments) / len(sentiments)
        except Exception as e:
            print(f"[Reddit Error] {e}")
            return None

    def _analyze_news(self, symbol: str):
        try:
            url = f"https://cryptopanic.com/api/v1/posts/?auth_token={self.news_api_key}&currencies={symbol}&public=true"
            response = requests.get(url)
            if response.status_code != 200:
                return None
            data = response.json()
            articles = data.get("results", [])[:10]
            if not articles:
                return None
            headlines = [item["title"] for item in articles]
            sentiments = [self.analyzer.polarity_scores(title)["compound"] for title in headlines]
            return sum(sentiments) / len(sentiments)
        except Exception as e:
            print(f"[News Error] {e}")
            return None

    def _interpret_score(self, score: float) -> str:
        if score > 0.3:
            return "positive"
        elif score < -0.3:
            return "negative"
        else:
            return "neutral"
