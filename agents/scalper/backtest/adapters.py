"""Adapters for backtesting data sources.

This module provides comprehensive data loading and preprocessing capabilities
for backtesting scalping strategies. It supports multiple data formats,
handles data validation, preprocessing, and provides utilities for realistic
backtesting scenarios including latency simulation and market impact modeling.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import pickle
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import pandas as pd

from ..data.market_store import TickRecord
from ..data.ws_client import Tick

logger = logging.getLogger(__name__)


class DataValidationError(Exception):
    """Raised when data validation fails."""

    pass


class DataLoadingError(Exception):
    """Raised when data loading fails."""

    pass


def load_csv_ticks(path: str, symbol: str) -> List[Tick]:
    """Load tick data from a CSV file for backtesting.

    The CSV is expected to contain at least the columns ``ts``,
    ``price`` and ``volume``. Additional columns are ignored.

    Args:
        path: Path to the CSV file.
        symbol: Symbol associated with the ticks.

    Returns:
        A list of :class:`Tick` objects.
    """
    ticks: List[Tick] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticks.append(
                Tick(
                    ts=float(row["ts"]),
                    price=float(row["price"]),
                    volume=float(row["volume"]),
                    side=row.get("side", "buy"),
                )
            )
    return ticks


class BacktestDataLoader:
    """Advanced data loader for backtesting with multiple format support."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.data_cache: Dict[str, List[TickRecord]] = {}
        self.validation_enabled = self.config.get("VALIDATE_DATA", True)
        self.preprocessing_enabled = self.config.get("PREPROCESS_DATA", True)

    def load_data(
        self,
        path: Union[str, Path],
        symbol: str,
        format_type: str = "auto",
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> List[TickRecord]:
        """Load tick data from various sources with comprehensive preprocessing.

        Args:
            path: Path to data file or directory
            symbol: Trading symbol
            format_type: Data format ('csv', 'json', 'parquet', 'pickle', 'auto')
            start_time: Start timestamp filter
            end_time: End timestamp filter

        Returns:
            List of TickRecord objects

        Raises:
            DataLoadingError: If data loading fails
            DataValidationError: If data validation fails
        """
        cache_key = f"{path}_{symbol}_{start_time}_{end_time}"
        if cache_key in self.data_cache:
            logger.info(f"Loading cached data for {symbol}")
            return self.data_cache[cache_key]

        try:
            # Auto-detect format if needed
            if format_type == "auto":
                format_type = self._detect_format(path)

            # Load data based on format
            if format_type == "csv":
                raw_data = self._load_csv_enhanced(path, symbol)
            elif format_type == "json":
                raw_data = self._load_json(path, symbol)
            elif format_type == "parquet":
                raw_data = self._load_parquet(path, symbol)
            elif format_type == "pickle":
                raw_data = self._load_pickle(path, symbol)
            elif format_type == "binance":
                raw_data = self._load_binance_trades(path, symbol)
            elif format_type == "coinbase":
                raw_data = self._load_coinbase_trades(path, symbol)
            else:
                raise DataLoadingError(f"Unsupported format: {format_type}")

            # Filter by time range
            if start_time or end_time:
                raw_data = self._filter_time_range(raw_data, start_time, end_time)

            # Validate data
            if self.validation_enabled:
                self._validate_data(raw_data, symbol)

            # Preprocess data
            if self.preprocessing_enabled:
                processed_data = self._preprocess_data(raw_data, symbol)
            else:
                processed_data = raw_data

            # Cache result
            self.data_cache[cache_key] = processed_data

            logger.info(f"Loaded {len(processed_data)} ticks for {symbol}")
            return processed_data

        except Exception as e:
            raise DataLoadingError(f"Failed to load data from {path}: {str(e)}")

    def _detect_format(self, path: Union[str, Path]) -> str:
        """Auto-detect data format from file extension."""
        path_obj = Path(path)
        suffix = path_obj.suffix.lower()

        format_map = {
            ".csv": "csv",
            ".json": "json",
            ".jsonl": "json",
            ".parquet": "parquet",
            ".pkl": "pickle",
            ".pickle": "pickle",
            ".gz": "csv",  # Assume compressed CSV
        }

        detected_format = format_map.get(suffix, "csv")
        logger.debug(f"Auto-detected format: {detected_format} for {path}")
        return detected_format

    def _load_csv_enhanced(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Enhanced CSV loader with flexible column mapping and error handling."""
        path_obj = Path(path)

        # Handle compressed files
        if path_obj.suffix == ".gz":
            open_func = gzip.open
            mode = "rt"
        else:
            open_func = open
            mode = "r"

        ticks = []

        try:
            with open_func(path, mode, encoding="utf-8") as f:
                # Detect delimiter
                sample = f.read(1024)
                f.seek(0)

                delimiter = ","
                if "\t" in sample:
                    delimiter = "\t"
                elif ";" in sample:
                    delimiter = ";"

                reader = csv.DictReader(f, delimiter=delimiter)

                # Map column names (flexible mapping)
                col_map = self._create_column_mapping(reader.fieldnames)

                for row_num, row in enumerate(reader, 1):
                    try:
                        tick = self._parse_csv_row(row, col_map, symbol)
                        if tick:
                            ticks.append(tick)
                    except (ValueError, KeyError) as e:
                        logger.warning(f"Error parsing row {row_num}: {e}")
                        continue

        except Exception as e:
            raise DataLoadingError(f"Error reading CSV file {path}: {e}")

        return ticks

    def _create_column_mapping(self, fieldnames: List[str]) -> Dict[str, str]:
        """Create flexible column mapping for various CSV formats."""
        if not fieldnames:
            raise DataLoadingError("CSV file has no header columns")

        # Common column name variations
        timestamp_cols = ["ts", "timestamp", "time", "datetime", "date_time", "unix_ts"]
        price_cols = ["price", "px", "last_price", "trade_price"]
        volume_cols = ["volume", "vol", "qty", "quantity", "size", "amount"]
        side_cols = ["side", "direction", "taker_side", "aggressor_side"]

        col_map = {}
        fieldnames_lower = [f.lower() for f in fieldnames]

        # Find timestamp column
        for ts_col in timestamp_cols:
            if ts_col in fieldnames_lower:
                col_map["timestamp"] = fieldnames[fieldnames_lower.index(ts_col)]
                break

        # Find price column
        for price_col in price_cols:
            if price_col in fieldnames_lower:
                col_map["price"] = fieldnames[fieldnames_lower.index(price_col)]
                break

        # Find volume column
        for vol_col in volume_cols:
            if vol_col in fieldnames_lower:
                col_map["volume"] = fieldnames[fieldnames_lower.index(vol_col)]
                break

        # Find side column (optional)
        for side_col in side_cols:
            if side_col in fieldnames_lower:
                col_map["side"] = fieldnames[fieldnames_lower.index(side_col)]
                break

        # Validate required columns
        required = ["timestamp", "price", "volume"]
        missing = [col for col in required if col not in col_map]
        if missing:
            raise DataLoadingError(f"Missing required columns: {missing}. Available: {fieldnames}")

        return col_map

    def _parse_csv_row(
        self, row: Dict[str, str], col_map: Dict[str, str], symbol: str
    ) -> Optional[TickRecord]:
        """Parse a single CSV row into a TickRecord."""
        try:
            # Parse timestamp
            ts_str = row[col_map["timestamp"]].strip()
            if ts_str.isdigit():
                # Unix timestamp
                timestamp = float(ts_str)
                # Convert to seconds if in milliseconds
                if timestamp > 1e12:
                    timestamp /= 1000
            else:
                # ISO format or other
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                timestamp = dt.timestamp()

            # Parse price and volume
            price = float(row[col_map["price"]].strip())
            volume = float(row[col_map["volume"]].strip())

            # Parse side (optional)
            side = "buy"  # default
            if "side" in col_map and col_map["side"] in row:
                side_str = row[col_map["side"]].strip().lower()
                if side_str in ["sell", "s", "ask", "sold"]:
                    side = "sell"
                elif side_str in ["buy", "b", "bid", "bought"]:
                    side = "buy"

            # Basic validation
            if price <= 0 or volume <= 0:
                return None

            return TickRecord(
                timestamp=timestamp, symbol=symbol, price=price, volume=volume, side=side
            )

        except (ValueError, KeyError) as e:
            logger.debug(f"Failed to parse row: {e}")
            return None

    def _load_json(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Load data from JSON/JSONL format."""
        ticks = []
        path_obj = Path(path)

        try:
            with open(path_obj, "r", encoding="utf-8") as f:
                if path_obj.suffix == ".jsonl":
                    # JSON Lines format
                    for line_num, line in enumerate(f, 1):
                        try:
                            data = json.loads(line.strip())
                            tick = self._parse_json_record(data, symbol)
                            if tick:
                                ticks.append(tick)
                        except json.JSONDecodeError as e:
                            logger.warning(f"Error parsing JSON line {line_num}: {e}")
                else:
                    # Regular JSON format
                    data = json.load(f)
                    if isinstance(data, list):
                        for record in data:
                            tick = self._parse_json_record(record, symbol)
                            if tick:
                                ticks.append(tick)
                    else:
                        # Single record
                        tick = self._parse_json_record(data, symbol)
                        if tick:
                            ticks.append(tick)

        except Exception as e:
            raise DataLoadingError(f"Error reading JSON file {path}: {e}")

        return ticks

    def _parse_json_record(self, record: Dict[str, Any], symbol: str) -> Optional[TickRecord]:
        """Parse a JSON record into a TickRecord."""
        try:
            # Flexible field mapping for JSON
            timestamp = record.get("ts") or record.get("timestamp") or record.get("time")
            price = record.get("price") or record.get("px") or record.get("p")
            volume = (
                record.get("volume") or record.get("vol") or record.get("v") or record.get("qty")
            )
            side = record.get("side", "buy")

            if timestamp is None or price is None or volume is None:
                return None

            # Convert timestamp if needed
            if isinstance(timestamp, str):
                if timestamp.isdigit():
                    timestamp = float(timestamp)
                    if timestamp > 1e12:
                        timestamp /= 1000
                else:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    timestamp = dt.timestamp()

            return TickRecord(
                timestamp=float(timestamp),
                symbol=symbol,
                price=float(price),
                volume=float(volume),
                side=str(side).lower(),
            )

        except (ValueError, KeyError, TypeError):
            return None

    def _load_parquet(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Load data from Parquet format using pandas."""
        try:
            df = pd.read_parquet(path)
            return self._dataframe_to_tick_records(df, symbol)
        except Exception as e:
            raise DataLoadingError(f"Error reading Parquet file {path}: {e}")

    def _load_pickle(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Load data from pickle format."""
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)

            if isinstance(data, pd.DataFrame):
                return self._dataframe_to_tick_records(data, symbol)
            elif isinstance(data, list):
                # Assume list of TickRecord or similar objects
                ticks = []
                for item in data:
                    if hasattr(item, "timestamp") and hasattr(item, "price"):
                        ticks.append(
                            TickRecord(
                                timestamp=float(item.timestamp),
                                symbol=symbol,
                                price=float(item.price),
                                volume=float(getattr(item, "volume", 1.0)),
                                side=getattr(item, "side", "buy"),
                            )
                        )
                return ticks
            else:
                raise DataLoadingError(f"Unsupported pickle data type: {type(data)}")

        except Exception as e:
            raise DataLoadingError(f"Error reading pickle file {path}: {e}")

    def _load_binance_trades(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Load Binance trade data format."""
        ticks = []

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line.strip())

                    # Binance trade format
                    tick = TickRecord(
                        timestamp=float(data["T"]) / 1000,  # Convert from ms
                        symbol=symbol,
                        price=float(data["p"]),
                        volume=float(data["q"]),
                        side="sell" if data["m"] else "buy",  # m=true means buyer is market maker
                    )
                    ticks.append(tick)

        except Exception as e:
            raise DataLoadingError(f"Error reading Binance trades file {path}: {e}")

        return ticks

    def _load_coinbase_trades(self, path: Union[str, Path], symbol: str) -> List[TickRecord]:
        """Load Coinbase trade data format."""
        ticks = []

        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line.strip())

                    if data.get("type") == "match":
                        tick = TickRecord(
                            timestamp=datetime.fromisoformat(
                                data["time"].replace("Z", "+00:00")
                            ).timestamp(),
                            symbol=symbol,
                            price=float(data["price"]),
                            volume=float(data["size"]),
                            side=data["side"],
                        )
                        ticks.append(tick)

        except Exception as e:
            raise DataLoadingError(f"Error reading Coinbase trades file {path}: {e}")

        return ticks

    def _dataframe_to_tick_records(self, df: pd.DataFrame, symbol: str) -> List[TickRecord]:
        """Convert pandas DataFrame to TickRecord list."""
        ticks = []

        # Create column mapping
        col_map = self._create_column_mapping(df.columns.tolist())

        for _, row in df.iterrows():
            try:
                timestamp = row[col_map["timestamp"]]
                if pd.isna(timestamp):
                    continue

                # Handle pandas timestamps
                if hasattr(timestamp, "timestamp"):
                    timestamp = timestamp.timestamp()
                else:
                    timestamp = float(timestamp)

                price = float(row[col_map["price"]])
                volume = float(row[col_map["volume"]])
                side = str(row.get(col_map.get("side", ""), "buy")).lower()

                if price <= 0 or volume <= 0:
                    continue

                tick = TickRecord(
                    timestamp=timestamp, symbol=symbol, price=price, volume=volume, side=side
                )
                ticks.append(tick)

            except (ValueError, KeyError):
                continue

        return ticks

    def _filter_time_range(
        self, ticks: List[TickRecord], start_time: Optional[float], end_time: Optional[float]
    ) -> List[TickRecord]:
        """Filter ticks by time range."""
        filtered = []
        for tick in ticks:
            if start_time and tick.timestamp < start_time:
                continue
            if end_time and tick.timestamp > end_time:
                continue
            filtered.append(tick)
        return filtered

    def _validate_data(self, ticks: List[TickRecord], symbol: str) -> None:
        """Validate loaded tick data."""
        if not ticks:
            raise DataValidationError("No valid ticks found in data")

        # Check for basic data quality issues
        errors = []

        # Check timestamp ordering
        for i in range(1, min(100, len(ticks))):  # Sample first 100
            if ticks[i].timestamp < ticks[i - 1].timestamp:
                errors.append(f"Timestamps not ordered at index {i}")
                break

        # Check for reasonable price/volume ranges
        prices = [t.price for t in ticks[:1000]]  # Sample
        volumes = [t.volume for t in ticks[:1000]]

        if max(prices) / min(prices) > 10:  # Price varies by more than 10x
            warnings.warn("Large price variations detected")

        if any(v <= 0 for v in volumes):
            errors.append("Zero or negative volumes found")

        if errors:
            raise DataValidationError(f"Data validation failed: {'; '.join(errors)}")

        logger.info(f"Data validation passed for {symbol}: {len(ticks)} ticks")

    def _preprocess_data(self, ticks: List[TickRecord], symbol: str) -> List[TickRecord]:
        """Preprocess and clean tick data."""
        if not ticks:
            return ticks

        processed = []

        # Sort by timestamp
        ticks.sort(key=lambda x: x.timestamp)

        # Remove duplicates
        seen = set()
        for tick in ticks:
            key = (tick.timestamp, tick.price, tick.volume)
            if key not in seen:
                seen.add(key)
                processed.append(tick)

        # Remove outliers (optional)
        if self.config.get("REMOVE_OUTLIERS", False):
            processed = self._remove_price_outliers(processed)

        # Aggregate sub-second trades (optional)
        if self.config.get("AGGREGATE_SUBSECOND", False):
            processed = self._aggregate_subsecond_trades(processed)

        logger.info(f"Preprocessed {len(ticks)} -> {len(processed)} ticks for {symbol}")
        return processed

    def _remove_price_outliers(self, ticks: List[TickRecord]) -> List[TickRecord]:
        """Remove obvious price outliers."""
        if len(ticks) < 10:
            return ticks

        # Calculate rolling median price
        window_size = min(50, len(ticks) // 4)
        filtered = []

        for i, tick in enumerate(ticks):
            start_idx = max(0, i - window_size // 2)
            end_idx = min(len(ticks), i + window_size // 2)

            window_prices = [t.price for t in ticks[start_idx:end_idx]]
            median_price = sorted(window_prices)[len(window_prices) // 2]

            # Remove prices that are more than 50% away from median
            if abs(tick.price - median_price) / median_price < 0.5:
                filtered.append(tick)

        return filtered

    def _aggregate_subsecond_trades(self, ticks: List[TickRecord]) -> List[TickRecord]:
        """Aggregate trades within the same second."""
        if not ticks:
            return ticks

        aggregated = []
        current_second = int(ticks[0].timestamp)
        current_trades = []

        for tick in ticks:
            tick_second = int(tick.timestamp)

            if tick_second == current_second:
                current_trades.append(tick)
            else:
                # Aggregate current second's trades
                if current_trades:
                    agg_tick = self._aggregate_tick_group(current_trades)
                    aggregated.append(agg_tick)

                current_second = tick_second
                current_trades = [tick]

        # Handle last group
        if current_trades:
            agg_tick = self._aggregate_tick_group(current_trades)
            aggregated.append(agg_tick)

        return aggregated

    def _aggregate_tick_group(self, ticks: List[TickRecord]) -> TickRecord:
        """Aggregate a group of ticks into a single tick."""
        if len(ticks) == 1:
            return ticks[0]

        # Volume-weighted average price
        total_volume = sum(t.volume for t in ticks)
        vwap = sum(t.price * t.volume for t in ticks) / total_volume

        # Use timestamp of first trade
        timestamp = ticks[0].timestamp

        # Determine dominant side
        buy_volume = sum(t.volume for t in ticks if t.side == "buy")
        sell_volume = sum(t.volume for t in ticks if t.side == "sell")
        side = "buy" if buy_volume >= sell_volume else "sell"

        return TickRecord(
            timestamp=timestamp, symbol=ticks[0].symbol, price=vwap, volume=total_volume, side=side
        )


def load_backtest_data(
    data_path: Union[str, Path],
    symbol: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> List[TickRecord]:
    """Convenience function to load backtest data with date filtering.

    Args:
        data_path: Path to data file or directory
        symbol: Trading symbol
        start_date: Start date in 'YYYY-MM-DD' format
        end_date: End date in 'YYYY-MM-DD' format
        config: Optional configuration

    Returns:
        List of TickRecord objects
    """
    loader = BacktestDataLoader(config)

    # Convert dates to timestamps
    start_ts = None
    end_ts = None

    if start_date:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        start_ts = start_dt.timestamp()

    if end_date:
        end_dt = datetime.strptime(end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_ts = end_dt.timestamp()

    return loader.load_data(data_path, symbol, start_time=start_ts, end_time=end_ts)


def prepare_scalping_dataset(ticks: List[TickRecord], config: Dict[str, Any]) -> List[TickRecord]:
    """Prepare tick data specifically for scalping strategy backtesting.

    Args:
        ticks: Raw tick data
        config: Scalping configuration

    Returns:
        Processed tick data optimized for scalping
    """
    if not ticks:
        return ticks

    # Sort by timestamp
    ticks.sort(key=lambda x: x.timestamp)

    # Filter by minimum volume if specified
    min_volume = config.get("SCALP_MIN_VOLUME", 0.0)
    if min_volume > 0:
        ticks = [t for t in ticks if t.volume >= min_volume]

    # Filter by trading hours if specified
    trading_hours = config.get("SCALP_TRADING_HOURS")
    if trading_hours:
        start_hour, end_hour = trading_hours
        ticks = [
            t for t in ticks if start_hour <= datetime.fromtimestamp(t.timestamp).hour < end_hour
        ]

    # Simulate realistic latency if specified
    latency_ms = config.get("SCALP_SIMULATED_LATENCY_MS", 0)
    if latency_ms > 0:
        latency_seconds = latency_ms / 1000
        for tick in ticks:
            tick.timestamp += latency_seconds

    logger.info(f"Prepared {len(ticks)} ticks for scalping backtest")
    return ticks


def validate_backtest_data(
    ticks: List[TickRecord], config: Dict[str, Any]
) -> Tuple[bool, List[str]]:
    """Validate that data is suitable for scalping backtests.

    Args:
        ticks: Tick data to validate
        config: Scalping configuration

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    if not ticks:
        issues.append("No tick data provided")
        return False, issues

    # Check data completeness
    min_ticks = config.get("BACKTEST_MIN_TICKS", 1000)
    if len(ticks) < min_ticks:
        issues.append(f"Insufficient data: {len(ticks)} < {min_ticks} ticks")

    # Check time span
    time_span = ticks[-1].timestamp - ticks[0].timestamp
    min_hours = config.get("BACKTEST_MIN_HOURS", 1)
    if time_span < min_hours * 3600:
        issues.append(f"Insufficient time span: {time_span/3600:.1f}h < {min_hours}h")

    # Check data quality
    gaps = []
    for i in range(1, min(1000, len(ticks))):  # Check first 1000 ticks
        gap = ticks[i].timestamp - ticks[i - 1].timestamp
        if gap > 60:  # Gap > 1 minute
            gaps.append(gap)

    if len(gaps) > len(ticks) * 0.1:  # More than 10% gaps
        issues.append(f"Too many large time gaps: {len(gaps)}")

    # Check price continuity
    price_jumps = 0
    for i in range(1, min(1000, len(ticks))):
        price_change = abs(ticks[i].price - ticks[i - 1].price) / ticks[i - 1].price
        if price_change > 0.05:  # 5% price jump
            price_jumps += 1

    if price_jumps > 10:
        issues.append(f"Excessive price jumps: {price_jumps}")

    is_valid = len(issues) == 0
    return is_valid, issues
