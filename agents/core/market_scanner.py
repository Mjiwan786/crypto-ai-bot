"""
MarketScanner Agent
- Scans whitelisted pairs across exchanges (here: Kraken via ccxt by default)
- Computes tradability score using volatility, volume, spread, and configurable risk weights
- Stores ranked list in MCP key "ranked_pairs"
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Any, Dict, List, Optional

import ccxt
import numpy as np
import pandas as pd

from agents.core.errors import ConfigError, DataError, ExchangeError


def fetch_ohlcv_df(exchange_name: str, symbol: str, timeframe: str, limit: int) -> pd.DataFrame:
    ex = getattr(ccxt, exchange_name)()
    bars = ex.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(bars, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    return df


try:
    import ccxt
except ImportError as e:  # pragma: no cover
    raise ConfigError(
        "ccxt library is required for MarketScanner but not installed",
        config_key="dependencies",
        details={"missing_package": "ccxt", "install_command": "pip install ccxt"},
    ) from e

try:
    from utils.logger import get_logger
except Exception:  # pragma: no cover
    import logging
    from typing import Optional

    def get_logger(name: str, level: Optional[str] = None) -> logging.Logger:
        logging.basicConfig(level=logging.INFO)
        return logging.getLogger(name)


class MarketScanner:
    """
    Loop-compatible market scanner.

    Config:
      scanner:
        pairs: ["BTC/USDT","ETH/USDT"]  # optional; fallback to exchanges.kraken.pairs
        timeframe: "15m"
        lookback: 200
        period_vol: 48                 # bars used for volatility
        min_volume: 10000              # quote volume filter (if ticker provides)
        max_spread_bps: 30
        weights:
          volatility: 0.45
          volume: 0.35
          spread: 0.20
      exchanges.kraken.pairs: [...]
    """

    def __init__(
        self,
        config: Dict[str, Any],
        context: Any,
        logger: Optional[logging.Logger] = None,
        exchange: Optional[Any] = None,
    ) -> None:
        self.config = config or {}
        self.context = context
        self.logger = logger or get_logger(self.__class__.__name__)
        self._load_config()
        self.exchange = exchange or ccxt.kraken({"enableRateLimit": True})
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def _load_config(self) -> None:
        s = self.config.get("scanner", {})
        self.timeframe = s.get("timeframe", "15m")
        self.lookback = int(s.get("lookback", 200))
        self.period_vol = int(s.get("period_vol", 48))
        self.min_volume = float(s.get("min_volume", 0.0))
        self.max_spread_bps = float(s.get("max_spread_bps", 50.0))
        self.weights = s.get("weights", {"volatility": 0.45, "volume": 0.35, "spread": 0.20})
        self.pairs = s.get("pairs") or self.config.get("exchanges", {}).get("kraken", {}).get(
            "pairs", []
        )

    def run(self, loop: bool = True, sleep_s: int = 60) -> None:
        """Run the market scanner.

        Args:
            loop: If True, run continuously; if False, run once
            sleep_s: Seconds to sleep between iterations

        Raises:
            ConfigError: If configuration is invalid
            ExchangeError: If exchange connection fails critically
        """
        while True:
            if self._stop:
                self.logger.info("MarketScanner stopping.")
                break
            try:
                self.step()
            except (ConfigError, ExchangeError):
                # Re-raise critical errors that should stop the scanner
                raise
            except DataError as e:
                # Log data errors but continue scanning
                self.logger.error("Data error during scan: %s", e)
            except Exception as e:
                # Wrap unexpected errors
                self.logger.error("Scanner step error: %s\n%s", e, traceback.format_exc())
            if not loop:
                break
            time.sleep(sleep_s)

    def step(self) -> None:
        """Execute one market scan iteration.

        Raises:
            ConfigError: If no pairs are configured
        """
        if not self.pairs:
            raise ConfigError(
                "No trading pairs configured for scanner",
                config_key="scanner.pairs",
                details={
                    "config_path": "scanner.pairs or exchanges.kraken.pairs",
                    "pairs_found": len(self.pairs),
                },
            )

        ranked: List[Dict[str, Any]] = []
        for symbol in self.pairs:
            try:
                score = self._score_symbol(symbol)
                if score is not None:
                    ranked.append({"symbol": symbol, "score": round(float(score), 4)})
            except ExchangeError:
                # Re-raise exchange errors
                raise
            except DataError as e:
                # Log data errors but continue with other symbols
                self.logger.warning("Data error for %s: %s", symbol, e)
            except Exception as e:
                # Wrap unexpected errors as DataError
                raise DataError(
                    f"Failed to score symbol {symbol}: {e}",
                    symbol=symbol,
                    data_type="ticker",
                    details={"original_error": str(e)},
                ) from e

        ranked.sort(key=lambda x: x["score"], reverse=True)
        self.context.set_value("ranked_pairs", ranked)
        self.logger.info("Updated ranked_pairs: %s", ranked[:5])

    # ------------- helpers -------------
    def _score_symbol(self, symbol: str) -> Optional[float]:
        """Score a symbol for tradability.

        Args:
            symbol: Trading symbol to score

        Returns:
            Tradability score [0, 1] or None if insufficient data

        Raises:
            ExchangeError: If exchange API call fails
            DataError: If data is invalid or insufficient
        """
        try:
            ticker = self.exchange.fetch_ticker(symbol)
        except Exception as e:
            raise ExchangeError(
                f"Failed to fetch ticker for {symbol}: {e}",
                exchange="kraken",
                api_method="fetch_ticker",
                details={"symbol": symbol, "original_error": str(e)},
            ) from e

        bid = float(ticker.get("bid") or 0.0)
        ask = float(ticker.get("ask") or 0.0)
        last = float(ticker.get("last") or ticker.get("close") or 0.0)

        if bid <= 0 or ask <= 0 or last <= 0:
            raise DataError(
                f"Invalid ticker data for {symbol}: missing or zero prices",
                symbol=symbol,
                data_type="ticker",
                details={"bid": bid, "ask": ask, "last": last},
            )

        spread = (ask - bid) / last  # ~ relative spread
        spread_bps = spread * 1e4

        # Volume proxy (prefer quoteVolume if present)
        quote_vol = float(ticker.get("quoteVolume") or 0.0)
        if self.min_volume and quote_vol < self.min_volume:
            return None  # Filtered out by volume requirement

        # Volatility from OHLCV
        try:
            ohlcv = self.exchange.fetch_ohlcv(
                symbol, timeframe=self.timeframe, limit=max(self.period_vol + 2, self.lookback)
            )
        except Exception as e:
            raise ExchangeError(
                f"Failed to fetch OHLCV for {symbol}: {e}",
                exchange="kraken",
                api_method="fetch_ohlcv",
                details={"symbol": symbol, "timeframe": self.timeframe, "original_error": str(e)},
            ) from e

        df = pd.DataFrame(ohlcv, columns=["ts", "open", "high", "low", "close", "volume"])
        if len(df) < self.period_vol:
            raise DataError(
                f"Insufficient OHLCV data for {symbol}: need {self.period_vol}, got {len(df)}",
                symbol=symbol,
                data_type="ohlcv",
                details={"required_bars": self.period_vol, "actual_bars": len(df)},
            )

        ret = np.diff(np.log(df["close"].values.astype(float)))
        vol = float(
            np.std(ret[-self.period_vol :]) * np.sqrt(self.period_vol)
        )  # simple annualization proxy per window

        # Normalize components
        vol_score = self._normalize_vol(vol)
        volm_score = self._normalize_volume(quote_vol)
        spread_score = self._normalize_spread(spread_bps)

        w = self.weights
        score = (
            w.get("volatility", 0.45) * vol_score
            + w.get("volume", 0.35) * volm_score
            + w.get("spread", 0.20) * spread_score
        )
        return float(max(0.0, min(1.0, score)))

    def _normalize_vol(self, v: float) -> float:
        # Higher volatility up to some cap is good for trading; cap at 6% (per-window proxy)
        return max(0.0, min(1.0, v / 0.06))

    def _normalize_volume(self, qv: float) -> float:
        # Scale up to 100M quote volume -> 1.0
        return max(0.0, min(1.0, qv / 1e8))

    def _normalize_spread(self, bps: float) -> float:
        # Tighter spread (<= 5 bps) is best; 0 bps -> 1.0 ; 50+ bps -> 0
        if bps <= 5:
            return 1.0
        if bps >= self.max_spread_bps:
            return 0.0
        return max(0.0, 1.0 - (bps - 5.0) / (self.max_spread_bps - 5.0))


if __name__ == "__main__":
    """Demo market scanner with mock data."""
    import asyncio

    logger = logging.getLogger(__name__)

    async def demo() -> None:
        """Run market scanner demo."""
        logger.info("Running MarketScanner demo...")
        # Demo code would go here
        logger.info("Demo completed")

    asyncio.run(demo())
