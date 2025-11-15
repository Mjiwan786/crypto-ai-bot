#!/usr/bin/env python3
"""
Redis Streams Monitor - Real-time Dashboard

Monitors critical Redis streams for go-live controls validation:
- signals:paper - Paper trading signals
- signals:live - Live trading signals (when in LIVE mode)
- metrics:circuit_breakers - Circuit breaker events
- metrics:mode_changes - Mode switching events
- metrics:emergency - Emergency stop events
- kraken:status - General status events

Usage:
    # Monitor all streams
    python scripts/monitor_redis_streams.py

    # Monitor specific streams
    python scripts/monitor_redis_streams.py --streams signals:paper kraken:status

    # Continuous tail mode
    python scripts/monitor_redis_streams.py --tail

    # Show last N entries
    python scripts/monitor_redis_streams.py --count 50
"""

import os
import sys
import redis
import ssl
import argparse
import time
import json
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from collections import defaultdict

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout.reconfigure(encoding='utf-8')

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


class StreamMonitor:
    """Real-time Redis streams monitor"""

    def __init__(self, redis_url: str):
        """Initialize monitor with Redis connection"""
        self.redis_url = redis_url
        self.redis = self._connect()
        self.stream_positions = {}  # Track last read position per stream

    def _connect(self) -> redis.Redis:
        """Connect to Redis Cloud with TLS"""
        use_tls = self.redis_url.startswith('rediss://')

        if use_tls:
            client = redis.from_url(
                self.redis_url,
                ssl_cert_reqs=ssl.CERT_NONE,
                decode_responses=True
            )
        else:
            client = redis.from_url(self.redis_url, decode_responses=True)

        # Test connection
        client.ping()
        return client

    def get_stream_info(self, stream: str) -> Dict[str, Any]:
        """Get stream information"""
        try:
            info = self.redis.xinfo_stream(stream)
            return {
                'length': info.get('length', 0),
                'first_entry': info.get('first-entry'),
                'last_entry': info.get('last-entry'),
                'groups': info.get('groups', 0)
            }
        except redis.ResponseError:
            return {'length': 0, 'exists': False}

    def get_active_streams(self) -> List[str]:
        """Get list of active monitoring streams"""
        patterns = [
            'signals:*',
            'metrics:*',
            'kraken:*',
            'ACTIVE_SIGNALS'
        ]

        streams = set()
        for pattern in patterns:
            keys = self.redis.keys(pattern)
            for key in keys:
                # Check if it's a stream
                try:
                    key_type = self.redis.type(key)
                    if key_type == 'stream':
                        streams.add(key)
                except:
                    pass

        return sorted(list(streams))

    def get_active_signal_stream(self) -> str:
        """Get the current active signal stream (paper or live)"""
        alias = self.redis.get('ACTIVE_SIGNALS')
        if alias:
            return alias if isinstance(alias, str) else alias.decode()
        return 'signals:paper'

    def read_stream(
        self,
        stream: str,
        count: int = 10,
        from_id: str = '-'
    ) -> List[tuple]:
        """
        Read entries from stream.

        Args:
            stream: Stream name
            count: Number of entries to read
            from_id: Starting ID ('-' for first, '$' for new only, or specific ID)

        Returns:
            List of (id, data) tuples
        """
        try:
            if from_id == '-':
                # Read last N entries
                entries = self.redis.xrevrange(stream, count=count)
                return list(reversed(entries))
            else:
                # Read from specific ID
                result = self.redis.xread({stream: from_id}, count=count, block=0)
                if result:
                    return result[0][1]
                return []
        except redis.ResponseError as e:
            if 'no such key' in str(e).lower():
                return []
            raise

    def tail_streams(
        self,
        streams: List[str],
        interval_ms: int = 1000
    ):
        """
        Tail multiple streams in real-time.

        Args:
            streams: List of stream names to monitor
            interval_ms: Polling interval in milliseconds
        """
        # Initialize positions
        positions = {}
        for stream in streams:
            # Start from latest
            positions[stream] = '$'

        print(f"\n{'='*80}")
        print(f"TAILING STREAMS (Ctrl+C to stop)")
        print(f"{'='*80}")
        print(f"Monitoring: {', '.join(streams)}")
        print(f"Interval: {interval_ms}ms")
        print(f"{'='*80}\n")

        try:
            while True:
                # Build XREAD command
                stream_dict = {stream: positions[stream] for stream in streams}

                result = self.redis.xread(
                    stream_dict,
                    count=10,
                    block=interval_ms
                )

                if result:
                    for stream_name, entries in result:
                        for entry_id, entry_data in entries:
                            # Update position
                            positions[stream_name] = entry_id

                            # Format and print
                            self._print_entry(stream_name, entry_id, entry_data)

        except KeyboardInterrupt:
            print("\n\nStopped tailing streams.")

    def _print_entry(self, stream: str, entry_id: str, data: Dict[str, Any]):
        """Print stream entry in formatted way"""
        timestamp = datetime.now().strftime('%H:%M:%S.%f')[:-3]

        # Determine severity/color
        severity = self._get_severity(stream, data)
        prefix = self._get_prefix(severity)

        print(f"{prefix} [{timestamp}] {stream} | {entry_id}")

        # Print data
        for key, value in data.items():
            # Try to parse JSON values
            try:
                if isinstance(value, str) and (value.startswith('{') or value.startswith('[')):
                    value = json.loads(value)
                    value = json.dumps(value, indent=2)
            except:
                pass

            print(f"    {key}: {value}")

        print()

    def _get_severity(self, stream: str, data: Dict[str, Any]) -> str:
        """Determine entry severity"""
        if 'emergency' in stream:
            return 'critical'
        if 'circuit_breaker' in stream:
            return 'error'
        if 'error' in str(data).lower():
            return 'error'
        if 'warning' in str(data).lower():
            return 'warning'
        return 'info'

    def _get_prefix(self, severity: str) -> str:
        """Get prefix symbol for severity"""
        prefixes = {
            'critical': '🚨',
            'error': '❌',
            'warning': '⚠️',
            'info': '✓'
        }
        return prefixes.get(severity, 'ℹ️')

    def show_dashboard(
        self,
        streams: Optional[List[str]] = None,
        count: int = 10
    ):
        """
        Show monitoring dashboard with stream statistics.

        Args:
            streams: Streams to monitor (None = all active streams)
            count: Number of recent entries to show per stream
        """
        if streams is None:
            streams = self.get_active_streams()

        print(f"\n{'='*80}")
        print(f"REDIS STREAMS MONITORING DASHBOARD")
        print(f"{'='*80}")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Redis: {self.redis_url.split('@')[1] if '@' in self.redis_url else 'localhost'}")

        # Show active signal stream
        active_stream = self.get_active_signal_stream()
        print(f"\n🎯 ACTIVE_SIGNALS → {active_stream}")

        print(f"\n{'='*80}")
        print(f"STREAM STATISTICS")
        print(f"{'='*80}\n")

        # Get info for each stream
        stats = []
        for stream in streams:
            info = self.get_stream_info(stream)
            if info.get('length', 0) > 0 or stream in ['signals:paper', 'signals:live', 'kraken:status']:
                stats.append({
                    'stream': stream,
                    'length': info.get('length', 0),
                    'exists': info.get('exists', info.get('length', 0) > 0)
                })

        # Sort by length (most active first)
        stats.sort(key=lambda x: x['length'], reverse=True)

        # Print stats table
        print(f"{'Stream':<40} {'Messages':<15} {'Status':<10}")
        print(f"{'-'*40} {'-'*15} {'-'*10}")

        for stat in stats:
            status = '✓ Active' if stat['exists'] else '○ Empty'
            print(f"{stat['stream']:<40} {stat['length']:<15} {status:<10}")

        # Show recent entries for each stream
        print(f"\n{'='*80}")
        print(f"RECENT ENTRIES (last {count} per stream)")
        print(f"{'='*80}\n")

        for stat in stats:
            if stat['length'] > 0:
                print(f"\n--- {stat['stream']} ---\n")

                entries = self.read_stream(stat['stream'], count=count)

                if not entries:
                    print("  (no entries)")
                    continue

                for entry_id, entry_data in entries:
                    self._print_entry(stat['stream'], entry_id, entry_data)

        print(f"{'='*80}\n")

    def check_health(self) -> Dict[str, Any]:
        """Check health of go-live control monitoring"""
        health = {
            'redis_connected': False,
            'active_signal_stream': None,
            'streams': {},
            'issues': [],
            'warnings': []
        }

        try:
            # Test Redis
            self.redis.ping()
            health['redis_connected'] = True

            # Get active signal stream
            health['active_signal_stream'] = self.get_active_signal_stream()

            # Check critical streams
            critical_streams = [
                'signals:paper',
                'kraken:status',
                'metrics:circuit_breakers',
                'metrics:emergency'
            ]

            for stream in critical_streams:
                info = self.get_stream_info(stream)
                health['streams'][stream] = {
                    'exists': info.get('exists', info.get('length', 0) > 0),
                    'length': info.get('length', 0)
                }

                # Check if stream exists
                if not health['streams'][stream]['exists'] and stream in ['signals:paper', 'kraken:status']:
                    health['issues'].append(f"Critical stream '{stream}' does not exist")

            # Check for recent emergency stops
            emergency_entries = self.read_stream('metrics:emergency', count=5)
            if emergency_entries:
                last_entry = emergency_entries[-1][1]
                if last_entry.get('event') == 'emergency_stop_activated':
                    health['warnings'].append("Emergency stop may be active - check status")

            # Check for recent circuit breakers
            breaker_entries = self.read_stream('metrics:circuit_breakers', count=10)
            if len(breaker_entries) > 5:
                health['warnings'].append(f"Frequent circuit breaker trips ({len(breaker_entries)} recent)")

        except Exception as e:
            health['issues'].append(f"Health check failed: {e}")

        return health

    def print_health_report(self):
        """Print health check report"""
        health = self.check_health()

        print(f"\n{'='*80}")
        print(f"GO-LIVE CONTROLS HEALTH CHECK")
        print(f"{'='*80}\n")

        # Redis connection
        status = "✓ Connected" if health['redis_connected'] else "❌ Disconnected"
        print(f"Redis: {status}")

        # Active signal stream
        stream = health['active_signal_stream'] or 'Unknown'
        print(f"Active Signals: {stream}")

        # Stream status
        print(f"\nCritical Streams:")
        for stream, info in health['streams'].items():
            status = "✓" if info['exists'] else "❌"
            print(f"  {status} {stream:<35} ({info['length']} messages)")

        # Issues
        if health['issues']:
            print(f"\n❌ Issues:")
            for issue in health['issues']:
                print(f"  - {issue}")

        # Warnings
        if health['warnings']:
            print(f"\n⚠️  Warnings:")
            for warning in health['warnings']:
                print(f"  - {warning}")

        # Overall status
        print(f"\n{'='*80}")
        if not health['issues']:
            print("✓ HEALTH CHECK PASSED")
        else:
            print(f"❌ HEALTH CHECK FAILED ({len(health['issues'])} issues)")
        print(f"{'='*80}\n")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Redis Streams Monitor for Go-Live Controls",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--streams',
        nargs='+',
        help='Specific streams to monitor (default: all active)'
    )

    parser.add_argument(
        '--count',
        type=int,
        default=10,
        help='Number of recent entries to show per stream (default: 10)'
    )

    parser.add_argument(
        '--tail',
        action='store_true',
        help='Tail mode - continuously monitor streams'
    )

    parser.add_argument(
        '--health',
        action='store_true',
        help='Run health check only'
    )

    parser.add_argument(
        '--redis-url',
        help='Redis URL (default: from REDIS_URL env var)'
    )

    args = parser.parse_args()

    # Get Redis URL
    redis_url = args.redis_url or os.getenv('REDIS_URL')
    if not redis_url:
        print("Error: REDIS_URL not set")
        print("Set REDIS_URL environment variable or use --redis-url")
        return 1

    try:
        # Initialize monitor
        monitor = StreamMonitor(redis_url)

        if args.health:
            # Health check only
            monitor.print_health_report()

        elif args.tail:
            # Tail mode
            streams = args.streams
            if not streams:
                # Default streams for tailing
                streams = [
                    'signals:paper',
                    'metrics:circuit_breakers',
                    'metrics:emergency',
                    'kraken:status'
                ]

                # Add signals:live if it exists
                if monitor.get_stream_info('signals:live').get('length', 0) > 0:
                    streams.append('signals:live')

            monitor.tail_streams(streams)

        else:
            # Dashboard mode (default)
            monitor.show_dashboard(streams=args.streams, count=args.count)

        return 0

    except redis.ConnectionError as e:
        print(f"\n❌ Redis connection failed: {e}")
        print("Check REDIS_URL and network connectivity")
        return 1

    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
