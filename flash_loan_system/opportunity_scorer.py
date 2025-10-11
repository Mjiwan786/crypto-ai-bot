"""
flash_loan_system/opportunity_scorer.py

Real-time opportunity scoring and filtering for flash-loan arbitrage.
Bridge between raw market data and decision-making — the first gate that
prevents the system from wasting cycles on low-quality opportunities.

Author: Crypto AI Bot Team
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field, ConfigDict, field_validator
from scipy import stats

# External infrastructure (present in your repo skeleton)
from ..agents.ml.predictor import Predictor
from ..mcp.schemas import Signal, MetricsTick  # noqa: F401  (used by downstream)
from ..config.loader import get_config
from ..utils.logger import get_logger
from ..utils.redis_client import RedisClient
from ..utils.performance import PerformanceTimer


# ───────────────────────────────────────────────────────────────────────────────
# Domain enums
# ───────────────────────────────────────────────────────────────────────────────

class OpportunityType(str, Enum):
    CROSS_EXCHANGE = "cross_exchange"
    DEX_CEX = "dex_cex"
    TRIANGULAR = "triangular"
    FLASH_LOAN = "flash_loan"
    STATISTICAL = "statistical"


class RejectionReason(str, Enum):
    LOW_CONFIDENCE = "low_confidence"
    LOW_SPREAD = "low_spread"
    THIN_LIQUIDITY = "thin_liquidity"
    HIGH_SLIPPAGE = "high_slippage"
    HIGH_GAS = "high_gas"
    EXECUTION_RISK = "execution_risk"
    INSUFFICIENT_PROFIT = "insufficient_profit"
    BLACKLISTED_ROUTE = "blacklisted_route"
    RATE_LIMITED = "rate_limited"
    STALE_DATA = "stale_data"
    INTERNAL_ERROR = "internal_error"


# ───────────────────────────────────────────────────────────────────────────────
# Data structures
# ───────────────────────────────────────────────────────────────────────────────

@dataclass
class RawOpportunity:
    """Raw arbitrage opportunity from market data"""
    id: str
    timestamp: datetime
    opportunity_type: OpportunityType
    pair: str

    # Price / spread
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    spread_bps: float  # positive means profitable (sell - buy)

    # Liquidity
    buy_liquidity: float
    sell_liquidity: float
    min_liquidity: float  # USD notional available at the quoted levels

    # Market context
    gas_price: float  # gwei
    block_number: Optional[int] = None
    market_volatility: float = 0.0

    # Route
    route_complexity: int = 1
    hop_count: int = 2
    estimated_gas: int = 150_000  # gas units

    # Data quality
    data_age_ms: float = 0.0
    confidence_raw: float = 1.0


@dataclass
class ScoredOpportunity:
    """Scored and enriched arbitrage opportunity"""
    raw_opportunity: RawOpportunity

    # Scores (0..1)
    profitability_score: float
    risk_score: float
    confidence_score: float
    liquidity_score: float
    execution_score: float
    overall_score: float

    # Decision
    accepted: bool
    rejection_reason: Optional[RejectionReason] = None

    # Estimates
    estimated_profit_bps: float = 0.0
    estimated_profit_usd: float = 0.0
    estimated_slippage_bps: float = 0.0
    estimated_gas_cost_usd: float = 0.0
    net_profit_bps: float = 0.0

    # Execution context
    priority_rank: int = 0
    processing_time_ms: float = 0.0
    expires_at: Optional[datetime] = None

    # Features for ML/downstream
    features: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """JSON-safe dictionary (enums->str, datetimes->ISO)."""
        d = asdict(self)
        d["raw_opportunity"]["timestamp"] = self.raw_opportunity.timestamp.isoformat()
        d["raw_opportunity"]["opportunity_type"] = self.raw_opportunity.opportunity_type.value
        if self.expires_at:
            d["expires_at"] = self.expires_at.isoformat()
        if self.rejection_reason:
            d["rejection_reason"] = self.rejection_reason.value
        return d


# ───────────────────────────────────────────────────────────────────────────────
# Config
# ───────────────────────────────────────────────────────────────────────────────

class ScoringConfig(BaseModel):
    """Configuration for opportunity scoring"""
    model_config = ConfigDict(validate_assignment=True, extra="ignore")

    # Hard thresholds
    min_spread_bps: float = Field(8.0, ge=1.0, le=1000.0)
    min_liquidity_usd: float = Field(50_000.0, ge=1_000.0)
    max_slippage_bps: float = Field(20.0, ge=1.0, le=200.0)
    max_gas_price_gwei: float = Field(100.0, ge=1.0, le=2_000.0)
    min_confidence: float = Field(0.65, ge=0.0, le=1.0)
    min_net_profit_bps: float = Field(5.0, ge=1.0, le=200.0)

    # Soft weights (≈1.0)
    profitability_weight: float = Field(0.35, ge=0.0, le=1.0)
    risk_weight: float = Field(0.25, ge=0.0, le=1.0)
    confidence_weight: float = Field(0.20, ge=0.0, le=1.0)
    liquidity_weight: float = Field(0.15, ge=0.0, le=1.0)
    execution_weight: float = Field(0.05, ge=0.0, le=1.0)

    # Performance
    max_processing_time_ms: float = Field(50.0, ge=1.0, le=2_000.0)
    max_opportunities_per_second: int = Field(100, ge=1, le=10_000)
    stale_data_threshold_ms: float = Field(5_000.0, ge=100.0)

    # ML
    use_ml_scoring: bool = True
    ml_model_timeout_ms: float = Field(20.0, ge=1.0, le=200.0)
    ml_confidence_threshold: float = Field(0.70, ge=0.0, le=1.0)

    # Features
    feature_lookback_minutes: int = Field(5, ge=1, le=60)
    volatility_window_minutes: int = Field(15, ge=1, le=240)

    @field_validator(
        "profitability_weight", "risk_weight", "confidence_weight",
        "liquidity_weight", "execution_weight"
    )
    @classmethod
    def _weights_warn_sum(cls, v, info):  # keep permissive, warn if off
        data = info.data or {}
        weights = [
            data.get("profitability_weight", 0.35),
            data.get("risk_weight", 0.25),
            data.get("confidence_weight", 0.20),
            data.get("liquidity_weight", 0.15),
            data.get("execution_weight", 0.05),
        ]
        s = sum(weights)
        if abs(s - 1.0) > 0.02:
            logging.getLogger(__name__).warning("Scoring weights sum to %.3f (expected ~1.0)", s)
        return v


# ───────────────────────────────────────────────────────────────────────────────
# Core scorer
# ───────────────────────────────────────────────────────────────────────────────

class OpportunityScorer:
    """
    Real-time opportunity scoring & filtering.
    Ensures only high-quality opportunities reach simulation/execution.
    """

    def __init__(self, config: Optional[ScoringConfig] = None):
        self.config = config or ScoringConfig()
        self.logger = get_logger(__name__)

        # Performance & stats
        self.timer = PerformanceTimer()
        self.stats: Dict[str, Any] = {
            "opportunities_processed": 0,
            "opportunities_accepted": 0,
            "opportunities_rejected": 0,
            "avg_processing_time_ms": 0.0,
            "rejection_reasons": {},
            "last_reset_time": time.time(),
        }

        # ML
        self.ml_predictor: Optional[Predictor] = None
        if self.config.use_ml_scoring:
            try:
                self.ml_predictor = Predictor()
                self.logger.info("ML predictor initialized for scoring")
            except Exception as e:
                self.logger.warning("Failed to initialize ML predictor: %s", e)
                self.config.use_ml_scoring = False

        # Redis bus
        self.redis_client: Optional[RedisClient] = None

        # Feature caches
        self.feature_cache: Dict[str, Dict[str, float]] = {}
        self.cache_ttl_seconds = 30

        # Rate limiting (token bucket)
        self._tb_capacity = float(self.config.max_opportunities_per_second)
        self._tb_tokens = self._tb_capacity
        self._tb_fill_rate_per_s = self._tb_capacity  # capacity per second
        self._tb_last_refill = time.monotonic()

        # Blacklist routes
        self.route_blacklist: set[str] = set()

        self.logger.info("OpportunityScorer initialized with config: %s", self.config.model_dump())

    # ── lifecycle ────────────────────────────────────────────────────────────

    async def initialize(self):
        """Initialize external resources (Redis, warm up ML)."""
        bot_config = get_config()
        try:
            self.redis_client = RedisClient(bot_config.redis)
            await self.redis_client.connect()
        except Exception as e:
            self.logger.error("Redis initialization failed: %s", e)
            self.redis_client = None  # work in degraded mode

        if self.ml_predictor:
            try:
                dummy = self._create_dummy_features()
                await asyncio.wait_for(
                    asyncio.to_thread(self.ml_predictor.score_flash_loan, dummy),
                    timeout=self.config.ml_model_timeout_ms / 1000.0,
                )
            except Exception as e:
                self.logger.warning("ML warmup failed: %s", e)

    async def shutdown(self):
        """Cleanup."""
        if self.redis_client:
            try:
                await self.redis_client.disconnect()
            except Exception:
                pass
        self.feature_cache.clear()
        self.logger.info("OpportunityScorer shutdown complete")

    # ── public API ───────────────────────────────────────────────────────────

    async def score_opportunity(
        self,
        raw_opportunity: RawOpportunity,
        context: Optional[Any] = None,
    ) -> ScoredOpportunity:
        start = time.perf_counter()
        try:
            if not self._rate_limit_allow():
                return self._reject(raw_opportunity, RejectionReason.RATE_LIMITED, start)

            if raw_opportunity.data_age_ms > self.config.stale_data_threshold_ms:
                return self._reject(raw_opportunity, RejectionReason.STALE_DATA, start)

            hard_fail = await self._apply_hard_filters(raw_opportunity)
            if hard_fail:
                so = self._reject(raw_opportunity, hard_fail, start)
                if context and hasattr(context, "record_decision"):
                    context.record_decision(
                        "flash_loan_reject",
                        {"reason": hard_fail.value, "opportunity_id": raw_opportunity.id,
                         "spread_bps": raw_opportunity.spread_bps},
                    )
                return so

            features = await self._extract_features(raw_opportunity)

            profitability_score = await self._score_profitability(raw_opportunity, features)
            risk_score = await self._score_risk(raw_opportunity, features)
            confidence_score = await self._score_confidence(raw_opportunity, features)
            liquidity_score = await self._score_liquidity(raw_opportunity, features)
            execution_score = await self._score_execution(raw_opportunity, features)

            overall = (
                profitability_score * self.config.profitability_weight
                + risk_score * self.config.risk_weight
                + confidence_score * self.config.confidence_weight
                + liquidity_score * self.config.liquidity_weight
                + execution_score * self.config.execution_weight
            )

            accepted = (overall >= 0.5) and (confidence_score >= self.config.min_confidence)

            est = await self._estimate_metrics(raw_opportunity, features)
            if accepted and est["net_profit_bps"] < self.config.min_net_profit_bps:
                accepted = False
                reject_reason = RejectionReason.INSUFFICIENT_PROFIT
            else:
                reject_reason = None if accepted else RejectionReason.LOW_CONFIDENCE

            elapsed_ms = (time.perf_counter() - start) * 1000.0
            scored = ScoredOpportunity(
                raw_opportunity=raw_opportunity,
                profitability_score=profitability_score,
                risk_score=risk_score,
                confidence_score=confidence_score,
                liquidity_score=liquidity_score,
                execution_score=execution_score,
                overall_score=overall,
                accepted=accepted,
                rejection_reason=reject_reason,
                estimated_profit_bps=est["profit_bps"],
                estimated_profit_usd=max(0.0, est["profit_usd"]),
                estimated_slippage_bps=est["slippage_bps"],
                estimated_gas_cost_usd=est["gas_cost_usd"],
                net_profit_bps=est["net_profit_bps"],
                processing_time_ms=elapsed_ms,
                expires_at=datetime.now(timezone.utc) + timedelta(seconds=30),
                features=features,
            )

            if context and hasattr(context, "record_decision"):
                if accepted:
                    context.record_decision(
                        "flash_loan_accept",
                        {
                            "opportunity_id": raw_opportunity.id,
                            "overall_score": overall,
                            "net_profit_bps": est["net_profit_bps"],
                        },
                    )
                else:
                    context.record_decision(
                        "flash_loan_reject",
                        {"opportunity_id": raw_opportunity.id, "reason": (reject_reason or RejectionReason.LOW_CONFIDENCE).value, "overall_score": overall},
                    )

            self._update_stats(scored)
            return scored

        except Exception as e:
            self.logger.exception("Error scoring opportunity %s: %s", raw_opportunity.id, e)
            return self._reject(raw_opportunity, RejectionReason.INTERNAL_ERROR, start)

    async def score_batch(
        self, opportunities: List[RawOpportunity], context: Optional[Any] = None
    ) -> List[ScoredOpportunity]:
        if not opportunities:
            return []
        tasks = [self.score_opportunity(o, context) for o in opportunities]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        ok: List[ScoredOpportunity] = [r for r in results if isinstance(r, ScoredOpportunity)]
        ok.sort(key=lambda x: x.overall_score, reverse=True)
        for i, o in enumerate(ok, start=1):
            o.priority_rank = i
        return ok

    async def publish_scored_opportunity(self, scored: ScoredOpportunity, stream_name: str = "arb:scored", maxlen: Optional[int] = None):
        """Publish to Redis stream if accepted."""
        if not self.redis_client or not scored.accepted:
            return
        try:
            payload = {
                "opportunity_id": scored.raw_opportunity.id,
                "timestamp": scored.raw_opportunity.timestamp.isoformat(),
                "pair": scored.raw_opportunity.pair,
                "overall_score": f"{scored.overall_score:.6f}",
                "net_profit_bps": f"{scored.net_profit_bps:.4f}",
                "priority_rank": scored.priority_rank,
                "expires_at": scored.expires_at.isoformat() if scored.expires_at else None,
                "data": json.dumps(scored.to_dict(), separators=(",", ":"), ensure_ascii=False),
            }
            # xadd with optional trim
            if maxlen and maxlen > 0:
                await self.redis_client.client.xadd(stream_name, payload, maxlen=maxlen, approximate=True)
            else:
                await self.redis_client.client.xadd(stream_name, payload)
        except Exception as e:
            self.logger.error("Failed to publish scored opportunity: %s", e)

    async def publish_batch(self, scored: List[ScoredOpportunity], stream_name: str = "arb:scored", maxlen: Optional[int] = None):
        accepted = [s for s in scored if s.accepted]
        if not accepted or not self.redis_client:
            return
        await asyncio.gather(*[self.publish_scored_opportunity(s, stream_name, maxlen=maxlen) for s in accepted], return_exceptions=True)
        self.logger.info("Published %d/%d accepted opportunities", len(accepted), len(scored))

    def get_stats(self) -> Dict[str, Any]:
        now = time.time()
        uptime_h = max(1e-6, (now - self.stats["last_reset_time"]) / 3600.0)
        processed = self.stats["opportunities_processed"]
        accepted = self.stats["opportunities_accepted"]
        rejected = self.stats["opportunities_rejected"]
        return {
            "uptime_hours": uptime_h,
            "opportunities_processed": processed,
            "opportunities_accepted": accepted,
            "opportunities_rejected": rejected,
            "acceptance_rate": (accepted / processed) if processed else 0.0,
            "avg_processing_time_ms": self.stats["avg_processing_time_ms"],
            "processing_rate_per_hour": processed / uptime_h if uptime_h > 0 else 0.0,
            "rejection_reasons": dict(self.stats["rejection_reasons"]),
            "ml_model_enabled": bool(self.config.use_ml_scoring and self.ml_predictor),
            "rate_limit_per_second": self.config.max_opportunities_per_second,
        }

    def reset_stats(self):
        self.stats = {
            "opportunities_processed": 0,
            "opportunities_accepted": 0,
            "opportunities_rejected": 0,
            "avg_processing_time_ms": 0.0,
            "rejection_reasons": {},
            "last_reset_time": time.time(),
        }

    # ── admin helpers ─────────────────────────────────────────────────────────

    def add_to_blacklist(self, buy_exchange: str, sell_exchange: str, pair: str):
        self.route_blacklist.add(f"{buy_exchange}-{sell_exchange}-{pair}")

    def remove_from_blacklist(self, buy_exchange: str, sell_exchange: str, pair: str):
        self.route_blacklist.discard(f"{buy_exchange}-{sell_exchange}-{pair}")

    def clear_blacklist(self):
        self.route_blacklist.clear()

    async def health_check(self) -> Dict[str, Any]:
        health = {"status": "healthy", "timestamp": datetime.now(timezone.utc).isoformat(), "components": {}}
        # Redis
        if self.redis_client:
            try:
                await self.redis_client.client.ping()
                health["components"]["redis"] = "healthy"
            except Exception as e:
                health["components"]["redis"] = f"unhealthy: {e}"
                health["status"] = "degraded"
        else:
            health["components"]["redis"] = "not_configured"
        # ML
        if self.ml_predictor and self.config.use_ml_scoring:
            try:
                await asyncio.wait_for(asyncio.to_thread(self.ml_predictor.score_flash_loan, self._create_dummy_features()), timeout=1.0)
                health["components"]["ml_model"] = "healthy"
            except Exception as e:
                health["components"]["ml_model"] = f"unhealthy: {e}"
                health["status"] = "degraded"
        else:
            health["components"]["ml_model"] = "disabled"
        # Performance
        stats = self.get_stats()
        health["components"]["performance"] = "degraded_latency" if stats["avg_processing_time_ms"] > self.config.max_processing_time_ms else "healthy"
        health["stats"] = stats
        return health

    # ── internals ────────────────────────────────────────────────────────────

    def _rate_limit_allow(self) -> bool:
        """Token bucket: allow if token available; refill by elapsed seconds."""
        now = time.monotonic()
        elapsed = now - self._tb_last_refill
        self._tb_last_refill = now
        self._tb_tokens = min(self._tb_capacity, self._tb_tokens + elapsed * self._tb_fill_rate_per_s)
        if self._tb_tokens >= 1.0:
            self._tb_tokens -= 1.0
            return True
        return False

    async def _apply_hard_filters(self, o: RawOpportunity) -> Optional[RejectionReason]:
        route_key = f"{o.buy_exchange}-{o.sell_exchange}-{o.pair}"
        if route_key in self.route_blacklist:
            return RejectionReason.BLACKLISTED_ROUTE
        if o.spread_bps < self.config.min_spread_bps:
            return RejectionReason.LOW_SPREAD
        if o.min_liquidity < self.config.min_liquidity_usd:
            return RejectionReason.THIN_LIQUIDITY
        if o.gas_price > self.config.max_gas_price_gwei:
            return RejectionReason.HIGH_GAS
        return None

    async def _extract_features(self, o: RawOpportunity) -> Dict[str, float]:
        # Better cache key: pair + minute bucket + route endpoints
        bucket = int(o.timestamp.timestamp() // 60)
        cache_key = f"{o.pair}:{o.buy_exchange}->{o.sell_exchange}:{bucket}"
        now = time.time()
        cached = self.feature_cache.get(cache_key)
        if cached and now - cached.get("_ts", 0.0) < self.cache_ttl_seconds:
            return cached

        feats: Dict[str, float] = {
            "spread_bps": float(o.spread_bps),
            "min_liquidity_usd": float(o.min_liquidity),
            "liquidity_ratio": float(o.buy_liquidity / o.sell_liquidity) if o.sell_liquidity > 0 else 1.0,
            "gas_price_gwei": float(o.gas_price),
            "route_complexity": float(o.route_complexity),
            "hop_count": float(o.hop_count),
            "estimated_gas": float(o.estimated_gas),
            "data_age_ms": float(o.data_age_ms),
            "confidence_raw": float(o.confidence_raw),
            "price_level": float((o.buy_price + o.sell_price) / 2.0),
            "price_impact": float(abs(o.buy_price - o.sell_price) / max(1e-9, min(o.buy_price, o.sell_price))),
            "hour_of_day": float(o.timestamp.hour),
            "day_of_week": float(o.timestamp.weekday()),
            "is_weekend": float(o.timestamp.weekday() >= 5),
            "minute_of_hour": float(o.timestamp.minute),
        }

        # Pull market context if Redis available (best-effort)
        try:
            if self.redis_client:
                pair_key = o.pair.replace("/", "-")
                # Trades (last 5 min)
                trade_stream = f"kraken:trade:{pair_key}"
                min_id = f"{int((o.timestamp - timedelta(minutes=5)).timestamp() * 1000)}-0"
                trades = await self.redis_client.client.xrange(trade_stream, min=min_id, count=100)
                prices, volumes = [], []
                for _, fields in trades:
                    blob = (fields.get(b"trades") or fields.get("trades"))
                    if blob:
                        data = json.loads(blob.decode() if isinstance(blob, (bytes, bytearray)) else blob)
                        for t in data:
                            prices.append(float(t.get("price", 0.0)))
                            volumes.append(float(t.get("volume", 0.0)))
                if prices:
                    feats["recent_price_mean"] = float(np.mean(prices))
                    feats["recent_price_std"] = float(np.std(prices))
                    feats["recent_volume_mean"] = float(np.mean(volumes) if volumes else 0.0)
                    feats["market_volatility"] = float(np.std(prices) / max(1e-9, np.mean(prices)))

                # Order books (last 10 snapshots)
                book_stream = f"kraken:book:{pair_key}"
                books = await self.redis_client.client.xrange(book_stream, count=10)
                spreads = []
                for _, fields in books:
                    blob = (fields.get(b"data") or fields.get("data"))
                    if blob:
                        data = json.loads(blob.decode() if isinstance(blob, (bytes, bytearray)) else blob)
                        if isinstance(data, dict) and "spread_bps" in data:
                            spreads.append(float(data["spread_bps"]))
                if spreads:
                    feats["avg_recent_spread"] = float(np.mean(spreads))
                    feats["spread_percentile"] = float(stats.percentileofscore(spreads, o.spread_bps) / 100.0)
        except Exception as e:
            self.logger.debug("Market context feature extraction failed: %s", e)

        # Defaults
        feats.setdefault("recent_price_mean", feats["price_level"])
        feats.setdefault("recent_price_std", 0.0)
        feats.setdefault("recent_volume_mean", 1000.0)
        feats.setdefault("market_volatility", float(o.market_volatility))
        feats.setdefault("avg_recent_spread", float(o.spread_bps))
        feats.setdefault("spread_percentile", 0.5)

        # Exchange reliability heuristics
        feats.update(self._exchange_features(o))

        feats["_ts"] = now
        self.feature_cache[cache_key] = feats
        return feats

    def _exchange_features(self, o: RawOpportunity) -> Dict[str, float]:
        # Could be moved to config
        reliability = {
            "kraken": 0.95,
            "coinbase": 0.90,
            "binance": 0.88,
            "uniswap": 0.80,
            "sushiswap": 0.75,
        }
        b = reliability.get(o.buy_exchange.lower(), 0.70)
        s = reliability.get(o.sell_exchange.lower(), 0.70)
        return {
            "buy_exchange_score": b,
            "sell_exchange_score": s,
            "exchange_score_diff": abs(b - s),
            "min_exchange_score": min(b, s),
        }

    # ── scoring components ───────────────────────────────────────────────────

    async def _score_profitability(self, o: RawOpportunity, f: Dict[str, float]) -> float:
        # Base from spread (capped)
        base = min(1.0, o.spread_bps / 50.0)  # 50 bps → 1.0
        # Fee roughness: 5 bps combined
        fee_bps = 5.0
        # Gas impact (bps over position; approximate with 25k default size)
        # Will be re-estimated in metrics using actual position sizing heuristic
        gas_cost_eth = o.gas_price * o.estimated_gas * 1e-9
        gas_cost_usd = gas_cost_eth * 2500.0  # configurable if you track ETH/USD
        pos_usd = max(1.0, min(o.min_liquidity * 0.1, 25_000.0))
        gas_bps = (gas_cost_usd / pos_usd) * 10_000.0
        net_spread = o.spread_bps - fee_bps - gas_bps
        net = 0.0 if net_spread <= 0 else min(1.0, net_spread / 30.0)
        # Volume factor: prefer deeper books
        vol = min(1.0, o.min_liquidity / 100_000.0)
        return base * 0.5 + net * 0.4 + vol * 0.1

    async def _score_risk(self, o: RawOpportunity, f: Dict[str, float]) -> float:
        liq = min(1.0, o.min_liquidity / 200_000.0)
        vol = max(0.0, 1.0 - f.get("market_volatility", 0.1) * 5.0)
        complexity = max(0.0, 1.0 - (o.route_complexity - 1) * 0.2)
        gas = max(0.0, 1.0 - o.gas_price / 200.0)
        exch = f.get("min_exchange_score", 0.7)
        return liq * 0.3 + vol * 0.25 + complexity * 0.2 + gas * 0.15 + exch * 0.1

    async def _score_confidence(self, o: RawOpportunity, f: Dict[str, float]) -> float:
        # ML if available
        if self.ml_predictor and self.config.use_ml_scoring:
            try:
                ml_feats = {k: v for k, v in f.items() if not k.startswith("_")}
                res = await asyncio.wait_for(
                    asyncio.to_thread(self.ml_predictor.score_flash_loan, ml_feats),
                    timeout=self.config.ml_model_timeout_ms / 1000.0,
                )
                if isinstance(res, dict) and "conf" in res:
                    ml_conf = float(res["conf"])
                    return ml_conf * 0.7 + o.confidence_raw * 0.3
            except asyncio.TimeoutError:
                self.logger.warning("ML model timeout — falling back to rule-based confidence")
            except Exception as e:
                self.logger.warning("ML model error — fallback: %s", e)
        # Rule-based
        freshness = max(0.0, 1.0 - o.data_age_ms / 10_000.0)
        spread_stability = f.get("spread_percentile", 0.5)  # proxy for relative stability
        return o.confidence_raw * 0.6 + freshness * 0.3 + spread_stability * 0.1

    async def _score_liquidity(self, o: RawOpportunity, f: Dict[str, float]) -> float:
        abs_liq = min(1.0, o.min_liquidity / 500_000.0)
        ratio = o.buy_liquidity / o.sell_liquidity if o.sell_liquidity > 0 else 1.0
        balance = 1.0 - min(0.5, abs(1.0 - ratio))
        recent_vol = min(1.0, f.get("recent_volume_mean", 1000.0) / 10_000.0)
        return abs_liq * 0.6 + balance * 0.3 + recent_vol * 0.1

    async def _score_execution(self, o: RawOpportunity, f: Dict[str, float]) -> float:
        gas = max(0.0, 1.0 - o.gas_price / 150.0)
        simplicity = max(0.0, 1.0 - max(0, o.hop_count - 2) * 0.15)
        freshness = max(0.0, 1.0 - o.data_age_ms / 5_000.0)
        latency = 0.8  # placeholder until you wire real exchange latencies
        return gas * 0.4 + simplicity * 0.3 + freshness * 0.2 + latency * 0.1

    async def _estimate_metrics(self, o: RawOpportunity, f: Dict[str, float]) -> Dict[str, float]:
        """Estimate slippage, fees, gas, position size and net profit."""
        # Position: conservative cap at 10% depth or 25k
        position_usd = max(100.0, min(o.min_liquidity * 0.10, 25_000.0))

        # Slippage heuristic vs depth
        if o.min_liquidity > 200_000:
            slippage_bps = 2.0
        elif o.min_liquidity > 100_000:
            slippage_bps = 4.0
        elif o.min_liquidity > 50_000:
            slippage_bps = 8.0
        else:
            slippage_bps = 15.0

        # Fees (maker+maker conservative)
        fee_bps = 5.0

        # Gas (USD) — default ETH price assumption; replace with live feed if available
        gas_cost_eth = o.gas_price * o.estimated_gas * 1e-9
        gas_cost_usd = gas_cost_eth * 2500.0

        gas_bps = (gas_cost_usd / max(1.0, position_usd)) * 10_000.0
        gross_bps = float(o.spread_bps)
        total_cost_bps = slippage_bps + fee_bps + gas_bps
        net_bps = gross_bps - total_cost_bps
        profit_usd = (net_bps / 10_000.0) * position_usd

        return {
            "profit_bps": gross_bps,
            "profit_usd": profit_usd,
            "slippage_bps": slippage_bps,
            "gas_cost_usd": gas_cost_usd,
            "net_profit_bps": net_bps,
        }

    # ── helpers ──────────────────────────────────────────────────────────────

    def _reject(self, raw: RawOpportunity, reason: RejectionReason, start_perf: float) -> ScoredOpportunity:
        elapsed_ms = (time.perf_counter() - start_perf) * 1000.0
        scored = ScoredOpportunity(
            raw_opportunity=raw,
            profitability_score=0.0,
            risk_score=0.0,
            confidence_score=0.0,
            liquidity_score=0.0,
            execution_score=0.0,
            overall_score=0.0,
            accepted=False,
            rejection_reason=reason,
            processing_time_ms=elapsed_ms,
            features={},
        )
        self._update_stats(scored)
        return scored

    def _create_dummy_features(self) -> Dict[str, float]:
        return {
            "spread_bps": 15.0,
            "min_liquidity_usd": 100_000.0,
            "gas_price_gwei": 30.0,
            "route_complexity": 1.0,
            "price_level": 45_000.0,
            "market_volatility": 0.05,
            "hour_of_day": 12.0,
            "day_of_week": 2.0,
        }

    def _update_stats(self, s: ScoredOpportunity):
        self.stats["opportunities_processed"] += 1
        if s.accepted:
            self.stats["opportunities_accepted"] += 1
        else:
            self.stats["opportunities_rejected"] += 1
            if s.rejection_reason:
                key = s.rejection_reason.value
                self.stats["rejection_reasons"][key] = self.stats["rejection_reasons"].get(key, 0) + 1
        # moving average
        n = self.stats["opportunities_processed"]
        prev = self.stats["avg_processing_time_ms"]
        self.stats["avg_processing_time_ms"] = prev + (s.processing_time_ms - prev) / max(1, n)


# ───────────────────────────────────────────────────────────────────────────────
# Legacy bridge (compat shim)
# ───────────────────────────────────────────────────────────────────────────────

def score_opportunity(context: Any, config: Dict[str, Any], feature_row: Dict[str, Any]) -> Dict[str, Any]:
    """
    Synchronous shim preserving older call sites.
    """
    cfg = ScoringConfig()
    flash_cfg = (config or {}).get("flash_loan_system", {})
    ai_cfg = flash_cfg.get("ai_scoring", {})
    arb_cfg = flash_cfg.get("arbitrage", {})
    if "min_confidence" in ai_cfg:
        cfg.min_confidence = float(ai_cfg["min_confidence"])
    if "min_spread" in arb_cfg:
        cfg.min_spread_bps = float(arb_cfg["min_spread"])

    raw = RawOpportunity(
        id=str(feature_row.get("id", f"opp_{int(time.time()*1000)}")),
        timestamp=datetime.now(timezone.utc),
        opportunity_type=OpportunityType.FLASH_LOAN,
        pair=str(feature_row.get("pair", "BTC/USD")),
        buy_exchange=str(feature_row.get("buy_exchange", "exchange_a")),
        sell_exchange=str(feature_row.get("sell_exchange", "exchange_b")),
        buy_price=float(feature_row.get("buy_price", 0.0)),
        sell_price=float(feature_row.get("sell_price", 0.0)),
        spread_bps=float(feature_row.get("spread", 0.0)),
        buy_liquidity=float(feature_row.get("buy_liquidity", 100_000.0)),
        sell_liquidity=float(feature_row.get("sell_liquidity", 100_000.0)),
        min_liquidity=float(feature_row.get("liquidity_depth", 100_000.0)),
        gas_price=float(feature_row.get("gas_price", 30.0)),
    )

    scorer = OpportunityScorer(cfg)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        result: ScoredOpportunity = loop.run_until_complete(scorer.score_opportunity(raw, context))
    finally:
        try:
            loop.run_until_complete(scorer.shutdown())
        finally:
            loop.close()

    out = {
        "conf": result.confidence_score,
        "overall_score": result.overall_score,
        "profitability_score": result.profitability_score,
        "risk_score": result.risk_score,
        "accepted": result.accepted,
        "net_profit_bps": result.net_profit_bps,
    }
    if not result.accepted:
        reason = result.rejection_reason.value if result.rejection_reason else "unknown"
        if context and hasattr(context, "record_decision"):
            context.record_decision("flash_loan_reject", {"reason": reason, "res": out})
        out["reason"] = reason
    else:
        if context and hasattr(context, "record_decision"):
            context.record_decision("flash_loan_accept", out)
    return out


# ───────────────────────────────────────────────────────────────────────────────
# Manual smoke (optional)
# ───────────────────────────────────────────────────────────────────────────────

async def _example_usage():
    config = ScoringConfig(min_spread_bps=10.0, min_liquidity_usd=50_000.0, min_confidence=0.7, use_ml_scoring=True, max_opportunities_per_second=50)
    scorer = OpportunityScorer(config)
    await scorer.initialize()

    now = datetime.now(timezone.utc)
    ops = [
        RawOpportunity(
            id=f"test_{i}",
            timestamp=now,
            opportunity_type=OpportunityType.CROSS_EXCHANGE,
            pair="BTC/USD",
            buy_exchange="kraken",
            sell_exchange="coinbase",
            buy_price=45_000.0,
            sell_price=45_000.0 + (i + 1) * 50.0,
            spread_bps=(i + 1) * 10.0,
            buy_liquidity=100_000.0,
            sell_liquidity=120_000.0,
            min_liquidity=100_000.0,
            gas_price=30.0 + i * 5.0,
        )
        for i in range(5)
    ]
    scored = await scorer.score_batch(ops)
    await scorer.publish_batch(scored, stream_name="arb:scored", maxlen=10_000)
    await scorer.shutdown()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(_example_usage())
