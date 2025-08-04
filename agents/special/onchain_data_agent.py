"""
On‑Chain Data Agent
--------------------

This agent fetches on‑chain metrics such as exchange inflows, miner
behaviour or net position changes.  These metrics can serve as input
features for the macro analysis and sentiment models.  The free tier of
services like Glassnode provides a limited subset of metrics which should
be sufficient to get started.

As a template, the current implementation provides a synchronous API
that returns dummy data.  Replace this with actual API calls (e.g. via
requests or an SDK) as needed.
"""

from __future__ import annotations

from typing import Dict

from config.config_loader import load_config


cfg = load_config()


class OnChainDataAgent:
    """Fetch on‑chain metrics from external services."""

    def __init__(self) -> None:
        # Set up authentication or API clients here
        pass

    def fetch_metrics(self) -> Dict[str, float]:
        """Return a dictionary of on‑chain metrics.

        Returns
        -------
        dict
            For example ``{'exchange_netflow': -300.0, 'miner_to_exchange': 50.0}``.
        """
        # Placeholder returns static dummy data
        return {
            'exchange_netflow': -500.0,
            'miner_to_exchange': 75.0,
        }