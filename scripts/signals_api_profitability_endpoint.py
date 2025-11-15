"""
Signals-API Profitability Endpoint Integration

Flask/FastAPI endpoint handlers for profitability metrics dashboard.

Exposes:
- GET /api/profitability/7d - 7-day metrics
- GET /api/profitability/30d - 30-day metrics
- GET /api/profitability/summary - Combined summary
- GET /api/profitability/signals - Recent adaptation signals
- GET /api/profitability/health - Monitor health status

Usage (Flask):
    from signals_api_profitability_endpoint import create_profitability_blueprint

    app = Flask(__name__)
    app.register_blueprint(create_profitability_blueprint(redis_url=...))

Usage (FastAPI):
    from signals_api_profitability_endpoint import create_profitability_router

    app = FastAPI()
    app.include_router(create_profitability_router(redis_url=...))

Author: Crypto AI Bot Team
Date: 2025-11-09
"""

import os
import json
import logging
from typing import Dict, Optional
from datetime import datetime

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

try:
    from flask import Blueprint, jsonify, request
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ============================================================================
# REDIS CLIENT
# ============================================================================

class ProfitabilityRedisClient:
    """Redis client for fetching profitability metrics."""

    def __init__(
        self,
        redis_url: Optional[str] = None,
        ssl_ca_cert: Optional[str] = None,
    ):
        self.redis_url = redis_url or os.getenv('REDIS_URL')
        self.ssl_ca_cert = ssl_ca_cert or os.getenv('REDIS_SSL_CA_CERT', 'config/certs/redis_ca.pem')

        if not REDIS_AVAILABLE:
            logger.error("redis-py not installed")
            self.client = None
            return

        if not self.redis_url:
            logger.error("REDIS_URL not provided")
            self.client = None
            return

        try:
            # Parse SSL
            if self.redis_url.startswith('rediss://'):
                self.client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                    ssl_ca_certs=self.ssl_ca_cert,
                )
            else:
                self.client = redis.from_url(
                    self.redis_url,
                    decode_responses=True,
                )

            # Test connection
            self.client.ping()
            logger.info("Connected to Redis for profitability metrics")

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.client = None

    def get_metrics_7d(self) -> Optional[Dict]:
        """Get latest 7-day metrics."""
        if not self.client:
            return None

        try:
            data = self.client.get('profitability:latest:7d')
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get 7d metrics: {e}")
            return None

    def get_metrics_30d(self) -> Optional[Dict]:
        """Get latest 30-day metrics."""
        if not self.client:
            return None

        try:
            data = self.client.get('profitability:latest:30d')
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get 30d metrics: {e}")
            return None

    def get_summary(self) -> Optional[Dict]:
        """Get dashboard summary."""
        if not self.client:
            return None

        try:
            data = self.client.get('profitability:dashboard:summary')
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get summary: {e}")
            return None

    def get_latest_signal(self) -> Optional[Dict]:
        """Get latest adaptation signal."""
        if not self.client:
            return None

        try:
            data = self.client.get('profitability:latest:signal')
            return json.loads(data) if data else None
        except Exception as e:
            logger.error(f"Failed to get signal: {e}")
            return None

    def get_recent_signals(self, count: int = 10) -> list:
        """Get recent adaptation signals from stream."""
        if not self.client:
            return []

        try:
            # Read last N entries from stream
            entries = self.client.xrevrange(
                'profitability:adaptation_signals',
                count=count
            )

            signals = []
            for entry_id, data in entries:
                signals.append({
                    'id': entry_id,
                    'timestamp': data.get('triggered_at'),
                    'action': data.get('action'),
                    'reason': data.get('reason'),
                    'severity': data.get('severity'),
                })

            return signals

        except Exception as e:
            logger.error(f"Failed to get recent signals: {e}")
            return []

    def get_metrics_history_7d(self, count: int = 100) -> list:
        """Get historical 7d metrics."""
        if not self.client:
            return []

        try:
            entries = self.client.xrevrange(
                'profitability:metrics:7d',
                count=count
            )

            history = []
            for entry_id, data in entries:
                history.append({
                    'timestamp': int(data.get('calculated_at', 0)),
                    'roi_pct': float(data.get('roi_pct', 0)),
                    'profit_factor': float(data.get('profit_factor', 0)),
                    'max_drawdown_pct': float(data.get('max_drawdown_pct', 0)),
                    'sharpe_ratio': float(data.get('sharpe_ratio', 0)),
                    'win_rate_pct': float(data.get('win_rate_pct', 0)),
                })

            return history

        except Exception as e:
            logger.error(f"Failed to get 7d history: {e}")
            return []


# ============================================================================
# FLASK BLUEPRINT
# ============================================================================

def create_profitability_blueprint(
    redis_url: Optional[str] = None,
    ssl_ca_cert: Optional[str] = None,
) -> Blueprint:
    """Create Flask blueprint for profitability endpoints."""

    if not FLASK_AVAILABLE:
        raise ImportError("Flask not installed")

    bp = Blueprint('profitability', __name__, url_prefix='/api/profitability')

    # Initialize Redis client
    redis_client = ProfitabilityRedisClient(redis_url=redis_url, ssl_ca_cert=ssl_ca_cert)

    @bp.route('/7d', methods=['GET'])
    def get_metrics_7d():
        """Get 7-day profitability metrics."""
        metrics = redis_client.get_metrics_7d()

        if not metrics:
            return jsonify({
                'error': 'Metrics not available',
                'data': None,
            }), 404

        return jsonify({
            'success': True,
            'data': metrics,
            'timestamp': int(datetime.now().timestamp()),
        })

    @bp.route('/30d', methods=['GET'])
    def get_metrics_30d():
        """Get 30-day profitability metrics."""
        metrics = redis_client.get_metrics_30d()

        if not metrics:
            return jsonify({
                'error': 'Metrics not available',
                'data': None,
            }), 404

        return jsonify({
            'success': True,
            'data': metrics,
            'timestamp': int(datetime.now().timestamp()),
        })

    @bp.route('/summary', methods=['GET'])
    def get_summary():
        """Get profitability summary for dashboard."""
        summary = redis_client.get_summary()

        if not summary:
            return jsonify({
                'error': 'Summary not available',
                'data': None,
            }), 404

        return jsonify({
            'success': True,
            'data': summary,
            'timestamp': int(datetime.now().timestamp()),
        })

    @bp.route('/signals', methods=['GET'])
    def get_signals():
        """Get recent adaptation signals."""
        count = request.args.get('count', default=10, type=int)
        signals = redis_client.get_recent_signals(count=count)

        return jsonify({
            'success': True,
            'data': signals,
            'count': len(signals),
            'timestamp': int(datetime.now().timestamp()),
        })

    @bp.route('/history/7d', methods=['GET'])
    def get_history_7d():
        """Get 7d metrics history."""
        count = request.args.get('count', default=100, type=int)
        history = redis_client.get_metrics_history_7d(count=count)

        return jsonify({
            'success': True,
            'data': history,
            'count': len(history),
            'timestamp': int(datetime.now().timestamp()),
        })

    @bp.route('/health', methods=['GET'])
    def get_health():
        """Get monitor health status."""
        summary = redis_client.get_summary()
        signal = redis_client.get_latest_signal()

        health = {
            'monitor_running': summary is not None,
            'last_update': summary.get('timestamp') if summary else None,
            'latest_signal': signal.get('action') if signal else None,
            'redis_connected': redis_client.client is not None,
        }

        status_code = 200 if health['monitor_running'] else 503

        return jsonify({
            'success': True,
            'data': health,
            'timestamp': int(datetime.now().timestamp()),
        }), status_code

    return bp


# ============================================================================
# FASTAPI ROUTER
# ============================================================================

def create_profitability_router(
    redis_url: Optional[str] = None,
    ssl_ca_cert: Optional[str] = None,
) -> APIRouter:
    """Create FastAPI router for profitability endpoints."""

    if not FASTAPI_AVAILABLE:
        raise ImportError("FastAPI not installed")

    router = APIRouter(prefix='/api/profitability', tags=['profitability'])

    # Initialize Redis client
    redis_client = ProfitabilityRedisClient(redis_url=redis_url, ssl_ca_cert=ssl_ca_cert)

    @router.get('/7d')
    async def get_metrics_7d():
        """Get 7-day profitability metrics."""
        metrics = redis_client.get_metrics_7d()

        if not metrics:
            raise HTTPException(status_code=404, detail='Metrics not available')

        return {
            'success': True,
            'data': metrics,
            'timestamp': int(datetime.now().timestamp()),
        }

    @router.get('/30d')
    async def get_metrics_30d():
        """Get 30-day profitability metrics."""
        metrics = redis_client.get_metrics_30d()

        if not metrics:
            raise HTTPException(status_code=404, detail='Metrics not available')

        return {
            'success': True,
            'data': metrics,
            'timestamp': int(datetime.now().timestamp()),
        }

    @router.get('/summary')
    async def get_summary():
        """Get profitability summary for dashboard."""
        summary = redis_client.get_summary()

        if not metrics:
            raise HTTPException(status_code=404, detail='Summary not available')

        return {
            'success': True,
            'data': summary,
            'timestamp': int(datetime.now().timestamp()),
        }

    @router.get('/signals')
    async def get_signals(count: int = 10):
        """Get recent adaptation signals."""
        signals = redis_client.get_recent_signals(count=count)

        return {
            'success': True,
            'data': signals,
            'count': len(signals),
            'timestamp': int(datetime.now().timestamp()),
        }

    @router.get('/history/7d')
    async def get_history_7d(count: int = 100):
        """Get 7d metrics history."""
        history = redis_client.get_metrics_history_7d(count=count)

        return {
            'success': True,
            'data': history,
            'count': len(history),
            'timestamp': int(datetime.now().timestamp()),
        }

    @router.get('/health')
    async def get_health():
        """Get monitor health status."""
        summary = redis_client.get_summary()
        signal = redis_client.get_latest_signal()

        health = {
            'monitor_running': summary is not None,
            'last_update': summary.get('timestamp') if summary else None,
            'latest_signal': signal.get('action') if signal else None,
            'redis_connected': redis_client.client is not None,
        }

        status_code = 200 if health['monitor_running'] else 503

        return {
            'success': True,
            'data': health,
            'timestamp': int(datetime.now().timestamp()),
        }

    return router


# ============================================================================
# EXAMPLE USAGE
# ============================================================================

if __name__ == '__main__':
    print("="*80)
    print("PROFITABILITY API INTEGRATION - EXAMPLE")
    print("="*80)

    # Example 1: Flask
    if FLASK_AVAILABLE:
        print("\n1. Flask Integration:")
        print("""
from flask import Flask
from signals_api_profitability_endpoint import create_profitability_blueprint

app = Flask(__name__)
app.register_blueprint(create_profitability_blueprint(
    redis_url=os.getenv('REDIS_URL'),
))

# Endpoints available:
# GET /api/profitability/7d
# GET /api/profitability/30d
# GET /api/profitability/summary
# GET /api/profitability/signals?count=10
# GET /api/profitability/history/7d?count=100
# GET /api/profitability/health

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
        """)

    # Example 2: FastAPI
    if FASTAPI_AVAILABLE:
        print("\n2. FastAPI Integration:")
        print("""
from fastapi import FastAPI
from signals_api_profitability_endpoint import create_profitability_router

app = FastAPI()
app.include_router(create_profitability_router(
    redis_url=os.getenv('REDIS_URL'),
))

# Endpoints available:
# GET /api/profitability/7d
# GET /api/profitability/30d
# GET /api/profitability/summary
# GET /api/profitability/signals?count=10
# GET /api/profitability/history/7d?count=100
# GET /api/profitability/health

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=8000)
        """)

    # Example 3: Test Redis client
    print("\n3. Testing Redis Client:")

    redis_url = os.getenv('REDIS_URL')
    if redis_url:
        client = ProfitabilityRedisClient(redis_url=redis_url)

        summary = client.get_summary()
        print(f"   Summary: {summary}")

        metrics_7d = client.get_metrics_7d()
        print(f"   7d Metrics: {metrics_7d}")

        signals = client.get_recent_signals(count=5)
        print(f"   Recent Signals: {len(signals)} entries")
    else:
        print("   [SKIP] REDIS_URL not set")

    print("\n" + "="*80)
