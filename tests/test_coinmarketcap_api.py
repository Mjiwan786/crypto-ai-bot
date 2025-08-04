import os
import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.getenv("COINMARKETCAP_API_KEY")
BASE_URL = os.getenv("COINMARKETCAP_BASE_URL", "https://pro-api.coinmarketcap.com")
headers = {"X-CMC_PRO_API_KEY": API_KEY}

def test_cmc_listings():
    url = f"{BASE_URL}/v1/cryptocurrency/listings/latest"
    params = {
        "start": 1,
        "limit": 10,
        "convert": "USD"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if response.status_code == 200 and "data" in data:
            print("✅ CoinMarketCap API connected successfully (free endpoint).")
            for coin in data["data"]:
                print(f" - {coin['name']} ({coin['symbol']}): ${coin['quote']['USD']['price']:.2f}")
        else:
            print(f"❌ API returned error: {data.get('status', {}).get('error_message')}")
    except Exception as e:
        print(f"❌ Exception: {e}")

if __name__ == "__main__":
    test_cmc_listings()
