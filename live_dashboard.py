#!/usr/bin/env python3
"""
Live Dashboard - Real-time monitoring of crypto-ai-bot metrics.
Displays: Bot health, Kraken WS stats, circuit breakers, latest trades & spreads.
"""

import asyncio
import os
import json
from datetime import datetime
from dotenv import load_dotenv
import redis.asyncio as redis

# Load production environment
load_dotenv('.env.prod')


class LiveDashboard:
    """Real-time dashboard for crypto-ai-bot metrics."""

    def __init__(self):
        self.redis_url = os.getenv('REDIS_URL')
        self.redis_cert = os.getenv('REDIS_TLS_CERT_PATH')
        self.client = None
        self.running = True

    async def connect(self):
        """Connect to Redis Cloud."""
        self.client = redis.from_url(
            self.redis_url,
            ssl_cert_reqs='required',
            ssl_ca_certs=self.redis_cert,
            socket_connect_timeout=5,
            socket_keepalive=True,
            decode_responses=False
        )
        await self.client.ping()

    async def get_health_metrics(self):
        """Get latest health metrics from kraken:health stream."""
        try:
            entries = await self.client.xrevrange('kraken:health', count=1)
            if entries:
                entry_id, data = entries[0]
                decoded = {k.decode(): v.decode() for k, v in data.items()}
                return decoded
            return {}
        except:
            return {}

    async def get_trade_data(self, pair):
        """Get latest trade for a pair."""
        try:
            stream_name = f'kraken:trade:{pair}'
            entries = await self.client.xrevrange(stream_name, count=1)
            if entries:
                entry_id, data = entries[0]
                decoded = {k.decode(): v.decode() for k, v in data.items()}
                trades = json.loads(decoded.get('trades', '[]'))
                if trades:
                    return trades[0]
            return None
        except:
            return None

    async def get_spread_data(self, pair):
        """Get latest spread for a pair."""
        try:
            stream_name = f'kraken:spread:{pair}'
            entries = await self.client.xrevrange(stream_name, count=1)
            if entries:
                entry_id, data = entries[0]
                decoded = {k.decode(): v.decode() for k, v in data.items()}
                return decoded
            return {}
        except:
            return {}

    async def get_stream_stats(self):
        """Get stream statistics."""
        stats = {}
        streams = [
            'kraken:trade:BTC-USD', 'kraken:trade:ETH-USD', 'kraken:trade:SOL-USD', 'kraken:trade:ADA-USD',
            'kraken:spread:BTC-USD', 'kraken:spread:ETH-USD', 'kraken:spread:SOL-USD', 'kraken:spread:ADA-USD',
            'kraken:book:ETH-USD', 'kraken:health', 'signals:paper', 'metrics:pnl:equity'
        ]

        for stream in streams:
            try:
                length = await self.client.xlen(stream)
                stats[stream] = length
            except:
                stats[stream] = 0

        return stats

    def clear_screen(self):
        """Clear terminal screen."""
        os.system('cls' if os.name == 'nt' else 'clear')

    def render_dashboard(self, health, trades, spreads, stats):
        """Render the dashboard to console."""
        self.clear_screen()

        print("="*80)
        print(" " * 25 + "CRYPTO-AI-BOT LIVE DASHBOARD")
        print("="*80)
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}" + " " * 30 + "Press Ctrl+C to exit")
        print("="*80)

        # Engine Health
        print("\n[ENGINE HEALTH]")
        print("-" * 80)
        if health:
            messages = health.get('messages_received', '0')
            errors = health.get('errors', '0')
            cb_trips = health.get('circuit_breaker_trips', '0')
            latency_avg = float(health.get('latency_avg', 0))
            latency_p95 = float(health.get('latency_p95', 0))
            latency_p99 = float(health.get('latency_p99', 0))
            redis_latency = float(health.get('redis_latency_ms', 0))

            status = "[RUNNING]" if int(messages) > 0 else "[IDLE]"
            print(f"Status: {status}")
            print(f"Messages Processed: {messages}")
            print(f"Errors: {errors}")
            print(f"Circuit Breaker Trips: {cb_trips}")
            print(f"Latency: avg {latency_avg:.1f}ms | p95 {latency_p95:.1f}ms | p99 {latency_p99:.1f}ms")
            print(f"Redis Latency: {redis_latency:.1f}ms")
        else:
            print("Status: [NO DATA] - Engine may not be running")

        # Market Data
        print("\n[MARKET DATA - LIVE TRADES]")
        print("-" * 80)
        print(f"{'Pair':<12} {'Side':<6} {'Volume':<12} {'Price':<15} {'Spread (bps)'}")
        print("-" * 80)

        pairs = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD']
        for pair in pairs:
            trade = trades.get(pair)
            spread = spreads.get(pair, {})

            if trade:
                side = trade.get('side', 'N/A').upper()
                volume = float(trade.get('volume', 0))
                price = float(trade.get('price', 0))
                spread_bps = spread.get('spread_bps', 'N/A')

                # Color coding for side
                side_display = f"[{side}]"

                print(f"{pair:<12} {side_display:<6} {volume:<12.4f} ${price:<14.2f} {spread_bps}")
            else:
                print(f"{pair:<12} {'N/A':<6} {'N/A':<12} {'N/A':<15} {'N/A'}")

        # Stream Statistics
        print("\n[REDIS STREAMS STATISTICS]")
        print("-" * 80)
        print(f"{'Stream':<40} {'Messages'}")
        print("-" * 80)

        # Group streams
        print("Trades:")
        for stream, count in stats.items():
            if 'trade' in stream:
                pair = stream.split(':')[-1]
                print(f"  {pair:<37} {count}")

        print("\nSpreads:")
        for stream, count in stats.items():
            if 'spread' in stream:
                pair = stream.split(':')[-1]
                print(f"  {pair:<37} {count}")

        print("\nOther:")
        for stream, count in stats.items():
            if 'trade' not in stream and 'spread' not in stream:
                name = stream
                print(f"  {name:<37} {count}")

        print("\n" + "="*80)
        print("Dashboard refreshes every 2 seconds")
        print("="*80)

    async def run(self):
        """Run the dashboard loop."""
        print("Connecting to Redis Cloud...")
        await self.connect()
        print("Connected! Starting dashboard...\n")

        await asyncio.sleep(1)  # Brief pause before first render

        try:
            while self.running:
                # Fetch all data
                health = await self.get_health_metrics()

                trades = {}
                spreads = {}
                for pair in ['BTC-USD', 'ETH-USD', 'SOL-USD', 'ADA-USD']:
                    trades[pair] = await self.get_trade_data(pair)
                    spreads[pair] = await self.get_spread_data(pair)

                stats = await self.get_stream_stats()

                # Render
                self.render_dashboard(health, trades, spreads, stats)

                # Wait before next update
                await asyncio.sleep(2)

        except KeyboardInterrupt:
            print("\n\nStopping dashboard...")
        finally:
            if self.client:
                await self.client.aclose()
            print("Dashboard stopped.")


async def main():
    """Main entry point."""
    dashboard = LiveDashboard()
    await dashboard.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nExiting...")
