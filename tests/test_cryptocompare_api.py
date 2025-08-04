import os
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv("CRYPTOCOMPARE_API_KEY")
BASE_URL = os.getenv("CRYPTOCOMPARE_BASE_URL", "https://min-api.cryptocompare.com")

headers = {"Authorization": f"Apikey {API_KEY}"}

def test_pricemulti():
    url = f"{BASE_URL}/data/pricemulti"
    params = {
        "fsyms": "ETH,DASH",
        "tsyms": "BTC,USD,EUR"
    }

    try:
        response = requests.get(url, headers=headers, params=params)
        data = response.json()

        if response.status_code == 200 and "ETH" in data:
            print("✅ CryptoCompare API connected successfully.")
            for coin, prices in data.items():
                print(f" - {coin}:")
                for sym, value in prices.items():
                    print(f"   ➤ {sym}: {value}")
        else:
            print(f"❌ API returned error: {data}")
    except Exception as e:
        print(f"❌ Exception occurred: {e}")

if __name__ == "__main__":
    test_pricemulti()
