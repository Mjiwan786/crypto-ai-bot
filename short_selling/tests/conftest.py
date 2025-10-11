"""
Pytest configuration for short_selling tests.
"""

import sys
import warnings
from pathlib import Path

# Suppress Pydantic deprecation warnings
warnings.filterwarnings("ignore", category=DeprecationWarning, module="pydantic")

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

def pytest_configure(config):
    """Configure pytest settings."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )