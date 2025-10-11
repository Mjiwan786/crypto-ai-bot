"""Health check utilities for the scalper.

These functions allow external monitors to verify that the scalper
components are alive and responsive. They can be extended to perform
deeper self‑tests.
"""


def ping() -> bool:
    """Return a truthy value indicating the service is alive.

    For now this function always returns ``True`` but could be
    extended to perform checks on external dependencies such as
    Redis connectivity or WebSocket subscriptions.
    """
    return True
