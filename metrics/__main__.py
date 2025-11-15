"""
Entry point for running metrics publisher as a module.

Usage:
    python -m metrics.publisher
    python -m metrics.publisher --once
"""

from .publisher import main
import asyncio

if __name__ == '__main__':
    asyncio.run(main())
