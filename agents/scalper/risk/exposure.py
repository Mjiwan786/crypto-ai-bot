"""
agents/scalper/risk/exposure.py

Exposure calculation and risk monitoring for portfolio positions.
All monetary values are in USD unless otherwise stated.
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from ..config_loader import KrakenScalpingConfig

# ------------------------------- Data Models -------------------------------


@dataclass
class ExposureMetrics:
    """Snapshot of current exposure metrics."""

    total_notional: float = 0.0  # sum(|size| * price) across positions
    net_exposure: float = 0.0  # long - short (USD)
    gross_exposure: float = 0.0  # long + short (USD)
    leverage: float = 0.0  # gross_exposure / equity
    concentration_ratio: float = 0.0  # largest position notional / total_notional
    position_count: int = 0
    timestamp: float = 0.0


@dataclass
class PositionExposure:
    """Per-position exposure details."""

    symbol: str
    size: float
    price: float
    notional_value: float
    percentage_of_portfolio: float
    risk_weight: float = 1.0  # heuristic risk weighting factor


# ---------------------------- Exposure Calculator ----------------------------


class ExposureCalculator:
    """
    Calculate and monitor portfolio exposure metrics.

    Handles:
    - Notional exposure calculation
    - Concentration risk monitoring
    - Leverage calculation
    - Risk-weighted & correlation-adjusted exposure
    """

    def __init__(self, config: KrakenScalpingConfig):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}")

        # Portfolio/equity context
        account_equity = getattr(getattr(config, "account", object()), "equity_usd", None)
        self.base_capital = float(
            account_equity
            if account_equity is not None
            else getattr(config, "base_capital", 10_000.0)
        )

        # Limits/knobs
        self.max_leverage = float(getattr(getattr(config, "risk", object()), "max_leverage", 3.0))
        self.max_total_exposure_usd = float(
            getattr(getattr(config, "risk", object()), "max_total_exposure_usd", 10_000.0)
        )
        # Concentration cap as a ratio of total portfolio notional (e.g., 0.5 = 50%)
        self.max_concentration_ratio = float(
            getattr(getattr(config, "risk", object()), "per_symbol_max_exposure", 1.0)
        )

        # Optional overrides from config
        rw = getattr(getattr(config, "risk", object()), "risk_weights", None)
        self.risk_weights: Dict[str, float] = (
            dict(rw)
            if isinstance(rw, dict)
            else {
                "BTC/USD": 1.0,  # Base
                "ETH/USD": 1.1,
                "SOL/USD": 1.5,
                "ADA/USD": 1.8,
            }
        )

        corr = getattr(getattr(config, "risk", object()), "correlation_matrix", None)
        self.correlation_matrix: Dict[tuple, float] = (
            dict(corr)
            if isinstance(corr, dict)
            else {
                ("BTC/USD", "ETH/USD"): 0.85,
                ("BTC/USD", "SOL/USD"): 0.75,
                ("BTC/USD", "ADA/USD"): 0.70,
                ("ETH/USD", "SOL/USD"): 0.80,
                ("ETH/USD", "ADA/USD"): 0.75,
                ("SOL/USD", "ADA/USD"): 0.85,
            }
        )

        self.logger.info(
            "ExposureCalculator initialized: equity=%.2f max_lev=%.2fx",
            self.base_capital,
            self.max_leverage,
        )

    # ------------------------------ Core Metrics ------------------------------

    def calculate_exposure_metrics(
        self, positions: Dict[str, Dict], current_prices: Optional[Dict[str, float]] = None
    ) -> ExposureMetrics:
        """
        Calculate comprehensive exposure metrics for current positions.

        Args:
            positions: {symbol: {"size": float, "avg_price": float, ...}, ...}
            current_prices: Optional {symbol: price}

        Returns:
            ExposureMetrics
        """
        try:
            total_notional = 0.0
            long_exposure = 0.0
            short_exposure = 0.0
            pos_exposures: List[PositionExposure] = []

            for symbol, position in (positions or {}).items():
                if not position:
                    continue
                size = float(position.get("size", 0.0))
                if size == 0.0:
                    continue

                avg_price = float(position.get("avg_price", 0.0))
                px = float((current_prices or {}).get(symbol, avg_price))
                if px <= 0.0:
                    # Fallback to avg_price, else skip
                    px = avg_price if avg_price > 0 else 0.0
                    if px <= 0.0:
                        self.logger.warning(
                            "Skipping exposure for %s due to non-positive price", symbol
                        )
                        continue

                notional = abs(size) * px
                total_notional += notional

                if size > 0:
                    long_exposure += notional
                else:
                    short_exposure += notional

                pos_exposures.append(
                    PositionExposure(
                        symbol=symbol,
                        size=size,
                        price=px,
                        notional_value=notional,
                        percentage_of_portfolio=0.0,  # filled after total known
                        risk_weight=float(self.risk_weights.get(symbol, 1.0)),
                    )
                )

            # Percentages per position
            if total_notional > 0:
                for pe in pos_exposures:
                    pe.percentage_of_portfolio = pe.notional_value / total_notional

            net_exposure = long_exposure - short_exposure
            gross_exposure = long_exposure + short_exposure
            equity = max(self.base_capital, 1e-9)
            leverage = gross_exposure / equity

            # Concentration: largest position / total
            concentration_ratio = 0.0
            if total_notional > 0 and pos_exposures:
                largest = max(pe.notional_value for pe in pos_exposures)
                concentration_ratio = largest / total_notional

            return ExposureMetrics(
                total_notional=total_notional,
                net_exposure=net_exposure,
                gross_exposure=gross_exposure,
                leverage=leverage,
                concentration_ratio=concentration_ratio,
                position_count=len(pos_exposures),
                timestamp=time.time(),
            )

        except Exception as e:
            self.logger.error("Error calculating exposure metrics: %s", e, exc_info=True)
            return ExposureMetrics(timestamp=time.time())

    def calculate_risk_weighted_exposure(
        self, positions: Dict[str, Dict], current_prices: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Sum of risk-weighted notionals: sum(|size| * price * risk_weight).
        """
        try:
            total = 0.0
            for symbol, position in (positions or {}).items():
                if not position:
                    continue
                size = float(position.get("size", 0.0))
                if size == 0.0:
                    continue

                avg_price = float(position.get("avg_price", 0.0))
                px = float((current_prices or {}).get(symbol, avg_price))
                if px <= 0.0:
                    px = avg_price if avg_price > 0 else 0.0
                    if px <= 0.0:
                        continue

                notional = abs(size) * px
                rw = float(self.risk_weights.get(symbol, 1.0))
                total += notional * rw
            return total

        except Exception as e:
            self.logger.error("Error calculating risk-weighted exposure: %s", e, exc_info=True)
            return 0.0

    def calculate_correlation_adjusted_risk(
        self, positions: Dict[str, Dict], current_prices: Optional[Dict[str, float]] = None
    ) -> float:
        """
        Correlation-adjusted portfolio risk proxy (sqrt of variance):
            total_var = sum_i (r_i^2) + 2 * sum_{i<j} (corr_ij * r_i * r_j)
        where r_i = |size_i| * price_i * risk_weight_i
        """
        try:
            # Build per-symbol risk terms
            symbols: List[str] = [
                s for s, p in (positions or {}).items() if float(p.get("size", 0.0)) != 0.0
            ]
            if len(symbols) <= 1:
                return self.calculate_risk_weighted_exposure(positions, current_prices)

            risk_terms: Dict[str, float] = {}
            for s in symbols:
                pos = positions[s]
                size = float(pos.get("size", 0.0))
                avg_price = float(pos.get("avg_price", 0.0))
                px = float((current_prices or {}).get(s, avg_price))
                if px <= 0.0:
                    px = avg_price if avg_price > 0 else 0.0
                    if px <= 0.0:
                        continue
                notional = abs(size) * px
                rw = float(self.risk_weights.get(s, 1.0))
                risk_terms[s] = notional * rw

            syms = list(risk_terms.keys())
            n = len(syms)
            if n == 0:
                return 0.0

            total_var = 0.0
            for i in range(n):
                ri = risk_terms[syms[i]]
                total_var += ri * ri  # variance term
                for j in range(i + 1, n):
                    rj = risk_terms[syms[j]]
                    corr = self._get_correlation(syms[i], syms[j])
                    total_var += 2.0 * corr * ri * rj  # covariance (i<j)

            return max(total_var, 0.0) ** 0.5

        except Exception as e:
            self.logger.error("Error calculating correlation-adjusted risk: %s", e, exc_info=True)
            return self.calculate_risk_weighted_exposure(positions, current_prices)

    # ------------------------------ Risk Checks ------------------------------

    def check_concentration_limits(
        self, positions: Dict[str, Dict], current_prices: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """
        Validate concentration at portfolio and individual position level.
        Uses concentration relative to TOTAL NOTIONAL, not base capital.
        """
        violations: List[str] = []
        try:
            metrics = self.calculate_exposure_metrics(positions, current_prices)
            total = metrics.total_notional

            # Overall concentration
            max_conc = self.max_concentration_ratio
            if total > 0 and metrics.concentration_ratio > max_conc:
                violations.append(
                    f"Concentration ratio {metrics.concentration_ratio:.1%} exceeds limit {max_conc:.1%}"
                )

            # Per-position concentration
            if total > 0:
                for symbol, position in (positions or {}).items():
                    if not position:
                        continue
                    size = float(position.get("size", 0.0))
                    if size == 0.0:
                        continue
                    avg_price = float(position.get("avg_price", 0.0))
                    px = float((current_prices or {}).get(symbol, avg_price))
                    if px <= 0.0:
                        px = avg_price if avg_price > 0 else 0.0
                        if px <= 0.0:
                            continue

                    notional = abs(size) * px
                    pct_of_total = notional / total
                    if pct_of_total > max_conc:
                        violations.append(
                            f"Position {symbol} ({pct_of_total:.1%} of portfolio) exceeds limit {max_conc:.1%}"
                        )

        except Exception as e:
            self.logger.error("Error checking concentration limits: %s", e, exc_info=True)
            violations.append(f"Error checking concentration: {str(e)}")

        return violations

    def check_leverage_limits(
        self, positions: Dict[str, Dict], current_prices: Optional[Dict[str, float]] = None
    ) -> List[str]:
        """
        Validate portfolio leverage ceilings (raw and risk-weighted).
        """
        violations: List[str] = []
        try:
            metrics = self.calculate_exposure_metrics(positions, current_prices)

            if metrics.leverage > self.max_leverage:
                violations.append(
                    f"Portfolio leverage {metrics.leverage:.2f}x exceeds limit {self.max_leverage:.2f}x"
                )

            risk_weighted_exposure = self.calculate_risk_weighted_exposure(
                positions, current_prices
            )
            equity = max(self.base_capital, 1e-9)
            risk_adjusted_leverage = risk_weighted_exposure / equity

            # Give headroom vs. max leverage for risk-adjusted view
            if risk_adjusted_leverage > self.max_leverage * 0.80:
                violations.append(
                    f"Risk-adjusted leverage {risk_adjusted_leverage:.2f}x exceeds limit {(self.max_leverage * 0.80):.2f}x"
                )

        except Exception as e:
            self.logger.error("Error checking leverage limits: %s", e, exc_info=True)
            violations.append(f"Error checking leverage: {str(e)}")

        return violations

    # --------------------------- Sizing Recommendations ---------------------------

    def get_position_sizing_recommendation(
        self,
        symbol: str,
        current_positions: Dict[str, Dict],
        target_notional: float,
        current_prices: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Provide a recommended size (units & notional) for adding to `symbol`,
        while respecting concentration, leverage, and total-exposure capacity.

        Returns:
            {
                "recommended_size": float,
                "recommended_notional": float,
                "target_notional": float,
                "scaling_factor": float,
                "new_leverage": float,
                "new_concentration": float,
                "risk_weight": float
            }
        """
        try:
            # Snapshot current
            current_metrics = self.calculate_exposure_metrics(current_positions, current_prices)
            total_before = current_metrics.total_notional
            equity = max(self.base_capital, 1e-9)

            # Price for the symbol
            px_default = 100.0
            px = float((current_prices or {}).get(symbol, px_default))

            if px <= 0.0:
                # cannot size without a positive price
                raise ValueError(f"Non-positive price for {symbol}")

            # Simulate adding target notional (do not mutate caller input)
            test_positions = copy.deepcopy(current_positions or {})
            existing = dict(test_positions.get(symbol, {"size": 0.0, "avg_price": px}))
            add_size = float(target_notional) / px
            existing["size"] = float(existing.get("size", 0.0)) + add_size
            existing["avg_price"] = px  # assume entry near current
            test_positions[symbol] = existing

            new_metrics = self.calculate_exposure_metrics(test_positions, current_prices)
            total_after = new_metrics.total_notional

            # Constraint 1: concentration cap (as % of total notional AFTER trade)
            # Desired: notional(symbol) / total_after <= max_conc
            symbol_notional_after = abs(existing["size"]) * px
            max_conc = self.max_concentration_ratio

            recommended_notional = float(target_notional)
            scaling_factor = 1.0

            if total_after > 0.0 and max_conc < 1.0:
                max_symbol_notional = max_conc * total_after
                if symbol_notional_after > max_symbol_notional:
                    # Solve for scale 'k' on the add so that (current_sym + k*target) <= max_conc * (total_before + k*target)
                    # Let cur_sym = |current_sym_notional|, t = target_notional
                    cur_sym_notional = (
                        abs(float(current_positions.get(symbol, {}).get("size", 0.0))) * px
                    )
                    t = float(target_notional)
                    # cur_sym + k*t <= max_conc * (total_before + k*t)
                    # => k * t - max_conc * k * t <= max_conc * total_before - cur_sym
                    # => k * t * (1 - max_conc) <= max_conc * total_before - cur_sym
                    denom = t * max(1e-9, (1.0 - max_conc))
                    numer = max(0.0, max_conc * total_before - cur_sym_notional)
                    k = min(1.0, numer / denom) if denom > 0 else 0.0
                    recommended_notional = max(0.0, k * t)
                    scaling_factor = (recommended_notional / t) if t > 0 else 0.0

                    # Recompute new metrics if we scaled
                    if scaling_factor < 1.0:
                        if recommended_notional == 0.0:
                            # nothing to add → early return with safe values
                            return {
                                "recommended_size": 0.0,
                                "recommended_notional": 0.0,
                                "target_notional": target_notional,
                                "scaling_factor": 0.0,
                                "new_leverage": current_metrics.leverage,
                                "new_concentration": current_metrics.concentration_ratio,
                                "risk_weight": float(self.risk_weights.get(symbol, 1.0)),
                            }
                        add_size = recommended_notional / px
                        existing["size"] = (
                            float(current_positions.get(symbol, {}).get("size", 0.0)) + add_size
                        )
                        test_positions[symbol] = existing
                        new_metrics = self.calculate_exposure_metrics(
                            test_positions, current_prices
                        )
                        total_after = new_metrics.total_notional

            # Constraint 2: total exposure capacity
            available_exposure_capacity = max(0.0, self.max_total_exposure_usd - total_before)
            if recommended_notional > available_exposure_capacity:
                recommended_notional = available_exposure_capacity
                scaling_factor = (
                    (recommended_notional / float(target_notional)) if target_notional > 0 else 0.0
                )

            # Constraint 3: leverage ceiling
            # gross_after = total_after, but if we scaled, recompute add_size from recommended_notional
            add_size = (recommended_notional / px) if px > 0 else 0.0
            gross_after = total_before + abs(add_size) * px
            lev_after = gross_after / equity
            if lev_after > self.max_leverage:
                # scale to fit leverage
                # desired gross_after <= max_leverage * equity  => abs(add)*px <= max_lev*equity - total_before
                room = max(0.0, self.max_leverage * equity - total_before)
                recommended_notional = min(recommended_notional, room)
                scaling_factor = (
                    (recommended_notional / float(target_notional)) if target_notional > 0 else 0.0
                )

            # Final outputs
            final_size = (recommended_notional / px) if px > 0 else 0.0

            # Compute final “new” metrics for reporting
            final_positions = copy.deepcopy(current_positions or {})
            if final_size > 0.0:
                cur = dict(final_positions.get(symbol, {"size": 0.0, "avg_price": px}))
                cur["size"] = float(cur.get("size", 0.0)) + final_size
                cur["avg_price"] = px
                final_positions[symbol] = cur
            final_metrics = self.calculate_exposure_metrics(final_positions, current_prices)

            return {
                "recommended_size": final_size,
                "recommended_notional": recommended_notional,
                "target_notional": float(target_notional),
                "scaling_factor": float(scaling_factor),
                "new_leverage": float(final_metrics.leverage),
                "new_concentration": float(final_metrics.concentration_ratio),
                "risk_weight": float(self.risk_weights.get(symbol, 1.0)),
            }

        except Exception as e:
            self.logger.error(
                "Error calculating position sizing recommendation: %s", e, exc_info=True
            )
            return {
                "recommended_size": 0.0,
                "recommended_notional": 0.0,
                "target_notional": float(target_notional),
                "scaling_factor": 0.0,
                "error": str(e),
            }

    # ------------------------------- Utilities -------------------------------

    def _get_correlation(self, symbol1: str, symbol2: str) -> float:
        """Fetch correlation between two symbols (symmetric, default 0.5)."""
        key1 = (symbol1, symbol2)
        key2 = (symbol2, symbol1)
        if key1 in self.correlation_matrix:
            return float(self.correlation_matrix[key1])
        if key2 in self.correlation_matrix:
            return float(self.correlation_matrix[key2])
        return 0.5
