# data_pipeline/market_scanner.py
import ccxt
import pandas as pd
from ta import add_all_ta_features

class UniversalCoinScanner:
    def __init__(self):
        self.exchanges = {
            'binance': ccxt.binance(),
            'kraken': ccxt.kraken(),
            'coinbase': ccxt.coinbasepro()
        }
        
    def fetch_universe(self):
        """Get top 300 coins by market cap"""
        all_coins = []
        for exchange in self.exchanges.values():
            markets = exchange.load_markets()
            tickers = exchange.fetch_tickers()
            
            for symbol, ticker in tickers.items():
                if ticker['quoteVolume'] > 1000000:  # $1M volume filter
                    all_coins.append({
                        'symbol': symbol,
                        'exchange': exchange.id,
                        'volume': ticker['quoteVolume'],
                        'market_cap': ticker['baseVolume'] * ticker['last']
                    })
        
        return pd.DataFrame(all_coins).nlargest(300, 'market_cap')

    def enrich_features(self, coin_df):
        """Add technical and on-chain features"""
        # Technical indicators
        coin_df = add_all_ta_features(
            coin_df, 
            open="open",
            high="high",
            low="low",
            close="close",
            volume="volume"
        )
        
        # Add liquidity metrics
        coin_df['spread_pct'] = (coin_df['ask'] - coin_df['bid']) / coin_df['ask']
        
        return coin_df