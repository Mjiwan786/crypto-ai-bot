#!/usr/bin/env python3
import os
import time
import pandas as pd
from typing import Dict, Optional, List
from pycoingecko import CoinGeckoAPI
from dotenv import load_dotenv

# Load environment variables from project root
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '..', '.env'))

class CoinGeckoAPIWrapper:
    def __init__(self, max_retries: int = 3):
        self.api_key = os.getenv("COINGECKO_API_KEY", "")
        self.base_url = "https://api.coingecko.com/api/v3" if not self.api_key else None
        self.cg = CoinGeckoAPI(api_key=self.api_key, base_url=self.base_url)
        self.max_retries = max_retries
        self.request_delay = 6.1
        self.last_request_time = 0
        
        if not self.api_key:
            print("ℹ️ Using free CoinGecko API (limited to 10-50 requests/minute)")

    def _enforce_rate_limit(self):
        elapsed = time.time() - self.last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)
        self.last_request_time = time.time()

    def _safe_api_call(self, func, *args, **kwargs):
        for attempt in range(self.max_retries):
            try:
                self._enforce_rate_limit()
                return func(*args, **kwargs)
            except Exception as e:
                print(f"Attempt {attempt + 1} failed: {str(e)}")
                if attempt == self.max_retries - 1:
                    raise
                time.sleep(5 ** attempt)

    def get_coin_list(self) -> List[Dict]:
        return self._safe_api_call(self.cg.get_coins_list)

    def get_price(self, coin_id: str, currency: str = 'usd') -> Optional[float]:
        data = self._safe_api_call(
            self.cg.get_price,
            ids=coin_id,
            vs_currencies=currency
        )
        return data.get(coin_id, {}).get(currency)

def test_connection():
    print("🔄 Testing CoinGecko API connection...")
    api = CoinGeckoAPIWrapper()
    
    try:
        btc_price = api.get_price('bitcoin')
        print(f"✅ Connection successful! BTC Price: ${btc_price:,.2f}")
    except Exception as e:
        print(f"❌ Connection failed: {str(e)}")

if __name__ == "__main__":
    test_connection()