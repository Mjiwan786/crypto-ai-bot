"""
Stream registry for centralized Redis stream name management.

Provides a single source of truth for stream names and validates against drift
across configuration files.
"""

import os
import re
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from .streams_schema import StreamsConfig


# Global registry instance
_streams_config: Optional[StreamsConfig] = None


def load_streams(path: str = "config/streams.yaml") -> StreamsConfig:
    """
    Load stream configuration from YAML file.
    
    Args:
        path: Path to streams.yaml file
        
    Returns:
        Validated StreamsConfig instance
        
    Raises:
        FileNotFoundError: If streams.yaml not found
        yaml.YAMLError: If YAML parsing fails
        ValueError: If validation fails
    """
    global _streams_config
    
    if _streams_config is not None:
        return _streams_config
    
    # Resolve path relative to project root
    if not os.path.isabs(path):
        # Find project root by looking for pyproject.toml
        current = Path(__file__).parent
        while current.parent != current:
            if (current / "pyproject.toml").exists():
                break
            current = current.parent
        
        path = current / path
    
    if not os.path.exists(path):
        raise FileNotFoundError(f"Streams config not found: {path}")
    
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    
    if 'streams' not in data:
        raise ValueError("Invalid streams.yaml: missing 'streams' key")
    
    _streams_config = StreamsConfig(**data['streams'])
    return _streams_config


def get_stream(name: str, **fmt_kwargs) -> str:
    """
    Get formatted stream name by key.
    
    Args:
        name: Stream name key (looks in publish then subscribe)
        **fmt_kwargs: Formatting parameters for placeholders like {symbol}
        
    Returns:
        Formatted stream name
        
    Raises:
        ValueError: If stream name not found or formatting fails
    """
    config = load_streams()
    
    # Look in publish first, then subscribe
    pattern = config.publish.get(name) or config.subscribe.get(name)
    
    if not pattern:
        available = list(config.publish.keys()) + list(config.subscribe.keys())
        raise ValueError(f"Stream '{name}' not found. Available: {available}")
    
    try:
        return pattern.format(**fmt_kwargs)
    except KeyError as e:
        raise ValueError(f"Missing required parameter for stream '{name}': {e}")


def get_all_streams() -> Dict[str, str]:
    """Get all stream patterns as a dictionary."""
    config = load_streams()
    return config.get_all_streams()


def assert_no_drift(reference_paths: List[str]) -> List[str]:
    """
    Check for stream name drift across configuration files.
    
    Args:
        reference_paths: List of YAML files to check against streams.yaml
        
    Returns:
        List of drift messages (empty if no drift found)
    """
    drift_messages = []
    
    try:
        # Load the canonical streams config
        canonical = load_streams()
        canonical_streams = canonical.get_all_streams()
    except Exception as e:
        return [f"Failed to load canonical streams config: {e}"]
    
    # More comprehensive regex to find stream-like patterns in YAML
    # Matches patterns like "kraken:trades:XBTUSD" or "signals:kraken:XBTUSD" or "noncanonical:stream"
    stream_pattern = re.compile(r'["\']([a-z]+:[a-z]+[^"\']*)["\']')
    
    for ref_path in reference_paths:
        if not os.path.exists(ref_path):
            drift_messages.append(f"Reference file not found: {ref_path}")
            continue
        
        try:
            with open(ref_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Find potential stream names in the file
            found_streams = stream_pattern.findall(content)
            
            for stream_name in found_streams:
                # Check if this stream matches any canonical pattern
                is_canonical = False
                
                # Check against all canonical patterns
                for canonical_name, canonical_pattern in canonical_streams.items():
                    # Try to match by checking if the found stream could be generated
                    # by substituting placeholders in the canonical pattern
                    try:
                        # Simple heuristic: if the stream starts with the same prefix
                        # or contains the same key components, consider it canonical
                        if (stream_name.startswith(canonical.prefix + canonical.sep) or
                            any(part in stream_name for part in canonical_pattern.split(':'))):
                            is_canonical = True
                            break
                    except Exception:
                        continue
                
                if not is_canonical:
                    drift_messages.append(
                        f"Non-canonical stream '{stream_name}' found in {ref_path}"
                    )
        
        except Exception as e:
            drift_messages.append(f"Error checking {ref_path}: {e}")
    
    return drift_messages


def reset_registry() -> None:
    """Reset the global registry (useful for testing)."""
    global _streams_config
    _streams_config = None
