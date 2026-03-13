"""
Tests for Sprint 3 on-chain data clients.

Tests all 4 data clients (Coinalyze, Binance Futures, DefiLlama, Fear & Greed)
with mocked HTTP responses.
"""
import asyncio
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp


class TestCoinalyzeClient(unittest.TestCase):
    """Tests for CoinalyzeClient."""

    def setUp(self):
        from market_data.onchain.coinalyze_client import CoinalyzeClient
        self.client = CoinalyzeClient()

    def tearDown(self):
        asyncio.run(self.client.close())

    def test_fetch_open_interest_happy_path(self):
        """Valid JSON returns correct OI data."""
        mock_response = [{"history": [{"o": 15000000000, "t": 1709000000}]}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_response):
                result = await self.client.fetch_open_interest("BTCUSD.6")
                self.assertIsNotNone(result)
                self.assertEqual(result["open_interest_usd"], 15000000000)

        asyncio.run(run())

    def test_fetch_open_interest_api_error(self):
        """API error returns None."""
        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=None):
                result = await self.client.fetch_open_interest("BTCUSD.6")
                self.assertIsNone(result)

        asyncio.run(run())

    def test_fetch_funding_rate_happy_path(self):
        """Valid funding rate data returns correctly."""
        mock_response = [{"history": [{"o": 0.0003, "p": 0.0002, "t": 1709000000}]}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_response):
                result = await self.client.fetch_funding_rate("BTCUSD.6")
                self.assertIsNotNone(result)
                self.assertEqual(result["funding_rate"], 0.0003)

        asyncio.run(run())

    def test_fetch_liquidations_happy_path(self):
        """Valid liquidation data returns correctly."""
        mock_response = [{"history": [{"l": 5000000, "s": 3000000, "t": 1709000000}]}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_response):
                result = await self.client.fetch_liquidations("BTCUSD.6")
                self.assertIsNotNone(result)
                self.assertEqual(result["liquidated_longs_usd"], 5000000)
                self.assertEqual(result["liquidated_shorts_usd"], 3000000)

        asyncio.run(run())

    def test_fetch_all_merges_data(self):
        """fetch_all merges all data into DerivativesSnapshot."""
        from market_data.onchain.coinalyze_client import DerivativesSnapshot

        async def mock_oi(sym):
            return {"open_interest_usd": 15e9, "timestamp": time.time()}

        async def mock_funding(sym):
            return {"funding_rate": 0.0003, "predicted_funding": 0.0002, "timestamp": time.time()}

        async def mock_liqs(sym):
            return {"liquidated_longs_usd": 5e6, "liquidated_shorts_usd": 3e6, "timestamp": time.time()}

        async def run():
            self.client.fetch_open_interest = mock_oi
            self.client.fetch_funding_rate = mock_funding
            self.client.fetch_liquidations = mock_liqs
            result = await self.client.fetch_all("BTCUSD.6")
            self.assertIsNotNone(result)
            self.assertIsInstance(result, DerivativesSnapshot)
            self.assertEqual(result.open_interest_usd, 15e9)
            self.assertEqual(result.funding_rate, 0.0003)

        asyncio.run(run())

    def test_fetch_all_partial_failure(self):
        """fetch_all returns snapshot even if some sources fail."""
        async def mock_oi(sym):
            return {"open_interest_usd": 15e9, "timestamp": time.time()}

        async def mock_fail(sym):
            return None

        async def run():
            self.client.fetch_open_interest = mock_oi
            self.client.fetch_funding_rate = mock_fail
            self.client.fetch_liquidations = mock_fail
            result = await self.client.fetch_all("BTCUSD.6")
            self.assertIsNotNone(result)
            self.assertEqual(result.open_interest_usd, 15e9)
            self.assertIsNone(result.funding_rate)

        asyncio.run(run())

    def test_fetch_all_total_failure(self):
        """fetch_all returns None if all sources fail."""
        async def mock_fail(sym):
            return None

        async def run():
            self.client.fetch_open_interest = mock_fail
            self.client.fetch_funding_rate = mock_fail
            self.client.fetch_liquidations = mock_fail
            result = await self.client.fetch_all("BTCUSD.6")
            self.assertIsNone(result)

        asyncio.run(run())

    def test_malformed_json(self):
        """Malformed response returns None."""
        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value="not json"):
                result = await self.client.fetch_open_interest("BTCUSD.6")
                self.assertIsNone(result)

        asyncio.run(run())


class TestBinanceFuturesClient(unittest.TestCase):
    """Tests for BinanceFuturesClient."""

    def setUp(self):
        from market_data.onchain.binance_futures_client import BinanceFuturesClient
        self.client = BinanceFuturesClient()

    def tearDown(self):
        asyncio.run(self.client.close())

    def test_fetch_funding_rate(self):
        """Valid funding rate response."""
        mock_data = [{"fundingRate": "0.00030000", "fundingTime": 1709000000000}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_data):
                result = await self.client.fetch_funding_rate("BTCUSDT")
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result["funding_rate"], 0.0003, places=6)

        asyncio.run(run())

    def test_fetch_open_interest(self):
        """Valid OI response."""
        mock_data = {"openInterest": "12345.678", "time": 1709000000000}

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_data):
                result = await self.client.fetch_open_interest("BTCUSDT")
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result["open_interest"], 12345.678)

        asyncio.run(run())

    def test_fetch_long_short_ratio(self):
        """Valid L/S ratio response."""
        mock_data = [{"longShortRatio": "1.250", "longAccount": "0.556", "shortAccount": "0.444", "timestamp": 1709000000000}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_data):
                result = await self.client.fetch_long_short_ratio("BTCUSDT")
                self.assertIsNotNone(result)
                self.assertAlmostEqual(result["long_short_ratio"], 1.25)

        asyncio.run(run())

    def test_fetch_positioning_merges(self):
        """fetch_positioning merges L/S, top trader, and taker data."""
        from market_data.onchain.binance_futures_client import PositioningSnapshot

        async def mock_ls(sym):
            return {"long_short_ratio": 1.5, "long_account": 0.6, "short_account": 0.4, "timestamp": time.time()}

        async def mock_top(sym):
            return {"long_ratio": 0.55, "short_ratio": 0.45, "timestamp": time.time()}

        async def mock_taker(sym):
            return {"taker_buy_volume": 1000, "taker_sell_volume": 800, "taker_buy_sell_ratio": 1.25, "timestamp": time.time()}

        async def run():
            self.client.fetch_long_short_ratio = mock_ls
            self.client.fetch_top_trader_ratio = mock_top
            self.client.fetch_taker_volume = mock_taker
            result = await self.client.fetch_positioning("BTCUSDT")
            self.assertIsNotNone(result)
            self.assertIsInstance(result, PositioningSnapshot)
            self.assertAlmostEqual(result.long_short_ratio, 1.5)
            self.assertAlmostEqual(result.taker_buy_sell_ratio, 1.25)

        asyncio.run(run())

    def test_api_error_returns_none(self):
        """API error returns None."""
        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=None):
                result = await self.client.fetch_funding_rate("BTCUSDT")
                self.assertIsNone(result)

        asyncio.run(run())


class TestDefiLlamaClient(unittest.TestCase):
    """Tests for DefiLlamaClient."""

    def setUp(self):
        from market_data.onchain.defillama_client import DefiLlamaClient
        self.client = DefiLlamaClient()

    def tearDown(self):
        asyncio.run(self.client.close())

    def test_fetch_total_tvl(self):
        """Valid TVL response."""
        mock_data = [{"tvl": 100e9, "date": 1709000000}, {"tvl": 102e9, "date": 1709086400}]

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_data):
                result = await self.client.fetch_total_tvl()
                self.assertIsNotNone(result)
                self.assertEqual(result["total_tvl_usd"], 102e9)
                self.assertAlmostEqual(result["tvl_change_24h_pct"], 2.0, places=1)

        asyncio.run(run())

    def test_fetch_stablecoin_mcap(self):
        """Valid stablecoin data."""
        mock_data = {"peggedAssets": [
            {"circulating": {"peggedUSD": 80e9}},
            {"circulating": {"peggedUSD": 30e9}},
        ]}

        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=mock_data):
                result = await self.client.fetch_stablecoin_mcap()
                self.assertIsNotNone(result)
                self.assertEqual(result, 110e9)

        asyncio.run(run())

    def test_fetch_macro_merges(self):
        """fetch_macro merges all data."""
        from market_data.onchain.defillama_client import MacroSnapshot

        async def mock_tvl():
            return {"total_tvl_usd": 100e9, "tvl_change_24h_pct": 1.5}

        async def mock_stable():
            return 110e9

        async def mock_dex():
            return 5e9

        async def run():
            self.client.fetch_total_tvl = mock_tvl
            self.client.fetch_stablecoin_mcap = mock_stable
            self.client.fetch_dex_volume = mock_dex
            result = await self.client.fetch_macro()
            self.assertIsNotNone(result)
            self.assertIsInstance(result, MacroSnapshot)
            self.assertEqual(result.total_tvl_usd, 100e9)
            self.assertEqual(result.dex_volume_24h_usd, 5e9)

        asyncio.run(run())

    def test_api_error_returns_none(self):
        """All failures returns None."""
        async def run():
            with patch.object(self.client, '_get', new_callable=AsyncMock, return_value=None):
                result = await self.client.fetch_macro()
                self.assertIsNone(result)

        asyncio.run(run())


class TestFearGreedClient(unittest.TestCase):
    """Tests for FearGreedClient."""

    def setUp(self):
        from market_data.onchain.fear_greed_client import FearGreedClient
        self.client = FearGreedClient()

    def tearDown(self):
        asyncio.run(self.client.close())

    def test_fetch_fear_greed_happy_path(self):
        """Valid F&G response."""
        from market_data.onchain.fear_greed_client import SentimentSnapshot

        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={
            "data": [{"value": "25", "value_classification": "Extreme Fear", "timestamp": "1709000000"}]
        })
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        async def run():
            self.client._session = mock_session
            result = await self.client.fetch_fear_greed()
            self.assertIsNotNone(result)
            self.assertIsInstance(result, SentimentSnapshot)
            self.assertEqual(result.fear_greed_index, 25)
            self.assertEqual(result.fear_greed_label, "Extreme Fear")

        asyncio.run(run())

    def test_fetch_fear_greed_empty_data(self):
        """Empty data array returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value={"data": []})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        async def run():
            self.client._session = mock_session
            result = await self.client.fetch_fear_greed()
            self.assertIsNone(result)

        asyncio.run(run())

    def test_fetch_fear_greed_http_error(self):
        """HTTP error returns None."""
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.closed = False
        mock_session.close = AsyncMock()
        mock_session.get = MagicMock(return_value=mock_resp)

        async def run():
            self.client._session = mock_session
            result = await self.client.fetch_fear_greed()
            self.assertIsNone(result)

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
