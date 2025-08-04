"""
Agent package
-------------

This package contains the core logic for each trading agent.  To keep the
project modular, each agent is implemented in its own module.  Agents can
share helper utilities and read configuration via the :mod:`config` package.

Adding a new strategy or data source?  Create a new module here and import
`load_config` from :mod:`config.config_loader` to access runtime settings.
"""

__all__ = [
    "flash_loan_advisor",
    "signal_analyst",
    "alert_handler",
    "macro_analyzer",
    "sentiment_model",
    "news_reactor",
    "drawdown_protector",
    "whale_watcher",
]