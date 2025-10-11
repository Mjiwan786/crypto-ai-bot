#!/usr/bin/env python3
"""
Health API launcher script.

Starts the FastAPI health monitoring service on the specified port.
"""

import argparse
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import uvicorn
from services.health_api.app import app


def main():
    """Launch the health API service."""
    parser = argparse.ArgumentParser(description="Launch Crypto AI Bot Health API")
    parser.add_argument(
        "--port", 
        type=int, 
        default=9400, 
        help="Port to run the API on (default: 9400)"
    )
    parser.add_argument(
        "--host",
        type=str,
        default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0)"
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development"
    )
    
    args = parser.parse_args()
    
    print("health_api ready")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )


if __name__ == "__main__":
    main()
