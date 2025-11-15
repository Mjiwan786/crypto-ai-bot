"""
Scheduler for Nightly Model Retraining

Runs nightly_retrain.py at a scheduled time each day (default: 2:00 AM UTC).

Features:
- Configurable schedule (cron-like)
- Retry logic on failure
- Logging and notifications
- Redis status publishing
- Graceful shutdown

Usage:
    # Run scheduler (default 2:00 AM UTC)
    python scripts/schedule_nightly_retrain.py

    # Custom schedule (3:30 AM)
    python scripts/schedule_nightly_retrain.py --hour 3 --minute 30

    # Run immediately then schedule
    python scripts/schedule_nightly_retrain.py --run-now

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import sys
import time
import logging
import subprocess
import argparse
from datetime import datetime, timedelta
from typing import Optional
import signal

# Add project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%S'
)
logger = logging.getLogger(__name__)


# ============================================================================
# SCHEDULER
# ============================================================================

class NightlyRetrainScheduler:
    """Schedule and execute nightly retraining."""

    def __init__(
        self,
        hour: int = 2,  # 2 AM UTC
        minute: int = 0,
        redis_url: Optional[str] = None,
        ssl_ca_cert: Optional[str] = None,
        max_retries: int = 3,
        retry_delay_minutes: int = 30,
    ):
        self.hour = hour
        self.minute = minute
        self.max_retries = max_retries
        self.retry_delay_minutes = retry_delay_minutes

        # Redis connection
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        self.ssl_ca_cert = ssl_ca_cert or os.getenv(
            'REDIS_SSL_CA_CERT',
            'config/certs/redis_ca.pem'
        )
        self.redis_client = None

        if REDIS_AVAILABLE and self.redis_url:
            self._connect_redis()

        # Shutdown flag
        self.shutdown_requested = False

        # Register signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info(
            f"NightlyRetrainScheduler initialized: "
            f"scheduled for {self.hour:02d}:{self.minute:02d} UTC"
        )

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.shutdown_requested = True

    def _connect_redis(self):
        """Connect to Redis."""
        try:
            if self.redis_url.startswith('rediss://'):
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    ssl_ca_certs=self.ssl_ca_cert,
                )
            else:
                self.redis_client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )

            self.redis_client.ping()
            logger.info("Connected to Redis for scheduler status")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.redis_client = None

    def _publish_status(self, status: str, details: Optional[str] = None):
        """Publish scheduler status to Redis."""
        if not self.redis_client:
            return

        try:
            data = {
                'status': status,
                'timestamp': int(time.time()),
                'next_run': self._get_next_run_timestamp(),
            }

            if details:
                data['details'] = details

            self.redis_client.set(
                'scheduler:nightly_retrain:status',
                str(data),
                ex=86400,  # 24 hour expiry
            )

            # Also add to stream
            self.redis_client.xadd(
                'scheduler:nightly_retrain:events',
                data,
                maxlen=100,
            )

        except Exception as e:
            logger.error(f"Failed to publish status: {e}")

    def _get_next_run_timestamp(self) -> int:
        """Get timestamp of next scheduled run."""
        now = datetime.utcnow()

        # Calculate next run time
        next_run = now.replace(hour=self.hour, minute=self.minute, second=0, microsecond=0)

        # If already past today's run time, schedule for tomorrow
        if next_run <= now:
            next_run += timedelta(days=1)

        return int(next_run.timestamp())

    def _seconds_until_next_run(self) -> int:
        """Calculate seconds until next scheduled run."""
        next_run = self._get_next_run_timestamp()
        now = int(time.time())
        return max(0, next_run - now)

    def run_retrain_now(self) -> bool:
        """Run retraining immediately."""

        logger.info("="*80)
        logger.info("RUNNING NIGHTLY RETRAIN NOW")
        logger.info("="*80)

        self._publish_status('running', 'Retraining started')

        # Run nightly_retrain.py
        retries = 0
        success = False

        while retries <= self.max_retries and not success and not self.shutdown_requested:
            try:
                logger.info(f"Attempt {retries + 1}/{self.max_retries + 1}...")

                # Execute subprocess
                result = subprocess.run(
                    [sys.executable, 'scripts/nightly_retrain.py'],
                    capture_output=True,
                    text=True,
                    timeout=3600,  # 1 hour timeout
                )

                if result.returncode == 0:
                    logger.info("Retraining completed successfully")
                    logger.info(f"Output:\n{result.stdout}")
                    success = True
                    self._publish_status('success', 'Retraining completed')
                else:
                    logger.error(f"Retraining failed with code {result.returncode}")
                    logger.error(f"Stderr:\n{result.stderr}")

                    retries += 1

                    if retries <= self.max_retries:
                        logger.info(f"Retrying in {self.retry_delay_minutes} minutes...")
                        time.sleep(self.retry_delay_minutes * 60)

            except subprocess.TimeoutExpired:
                logger.error("Retraining timed out after 1 hour")
                retries += 1

                if retries <= self.max_retries:
                    logger.info(f"Retrying in {self.retry_delay_minutes} minutes...")
                    time.sleep(self.retry_delay_minutes * 60)

            except Exception as e:
                logger.error(f"Retraining error: {e}")
                retries += 1

                if retries <= self.max_retries:
                    logger.info(f"Retrying in {self.retry_delay_minutes} minutes...")
                    time.sleep(self.retry_delay_minutes * 60)

        if not success:
            logger.error(f"Retraining failed after {self.max_retries + 1} attempts")
            self._publish_status('failed', f'Failed after {self.max_retries + 1} attempts')

        return success

    def run_scheduler(self, run_immediately: bool = False):
        """Run scheduler loop."""

        logger.info("="*80)
        logger.info("NIGHTLY RETRAIN SCHEDULER - START")
        logger.info("="*80)
        logger.info(f"Schedule: {self.hour:02d}:{self.minute:02d} UTC daily")

        # Run immediately if requested
        if run_immediately:
            logger.info("\nRunning immediate retrain...")
            self.run_retrain_now()

        # Scheduler loop
        while not self.shutdown_requested:
            try:
                # Calculate time until next run
                seconds_until_next = self._seconds_until_next_run()
                next_run_time = datetime.utcfromtimestamp(self._get_next_run_timestamp())

                logger.info(
                    f"\nNext run scheduled: {next_run_time.strftime('%Y-%m-%d %H:%M:%S')} UTC "
                    f"(in {seconds_until_next // 3600}h {(seconds_until_next % 3600) // 60}m)"
                )

                self._publish_status('idle', f'Next run: {next_run_time.isoformat()}')

                # Sleep until next run (with periodic wake-ups to check shutdown)
                sleep_interval = 60  # Wake up every minute to check shutdown
                slept = 0

                while slept < seconds_until_next and not self.shutdown_requested:
                    time.sleep(min(sleep_interval, seconds_until_next - slept))
                    slept += sleep_interval

                # Check if shutdown requested
                if self.shutdown_requested:
                    break

                # Run retraining
                logger.info("\n" + "="*80)
                logger.info(f"SCHEDULED RUN: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC")
                logger.info("="*80)

                self.run_retrain_now()

                # Small sleep to avoid immediate re-run
                time.sleep(60)

            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                self._publish_status('error', str(e))
                time.sleep(300)  # 5 minute sleep on error

        logger.info("\n" + "="*80)
        logger.info("NIGHTLY RETRAIN SCHEDULER - STOPPED")
        logger.info("="*80)

        self._publish_status('stopped', 'Scheduler stopped')


# ============================================================================
# MAIN
# ============================================================================

def main():
    """Main execution."""

    parser = argparse.ArgumentParser(description='Schedule nightly model retraining')

    parser.add_argument(
        '--hour',
        type=int,
        default=2,
        help='Hour to run (0-23, UTC). Default: 2 (2 AM UTC)'
    )

    parser.add_argument(
        '--minute',
        type=int,
        default=0,
        help='Minute to run (0-59). Default: 0'
    )

    parser.add_argument(
        '--run-now',
        action='store_true',
        help='Run immediately, then continue with schedule'
    )

    parser.add_argument(
        '--max-retries',
        type=int,
        default=3,
        help='Maximum retry attempts on failure. Default: 3'
    )

    args = parser.parse_args()

    # Validate inputs
    if not (0 <= args.hour <= 23):
        logger.error(f"Invalid hour: {args.hour} (must be 0-23)")
        sys.exit(1)

    if not (0 <= args.minute <= 59):
        logger.error(f"Invalid minute: {args.minute} (must be 0-59)")
        sys.exit(1)

    # Create scheduler
    scheduler = NightlyRetrainScheduler(
        hour=args.hour,
        minute=args.minute,
        max_retries=args.max_retries,
    )

    # Run scheduler
    scheduler.run_scheduler(run_immediately=args.run_now)


if __name__ == '__main__':
    main()
