"""
Pydantic v2 schema for Redis stream configuration validation.

Validates stream naming consistency and ensures all streams contain the expected prefix.
"""

from typing import Dict, Any
from pydantic import BaseModel, Field, field_validator


class StreamsConfig(BaseModel):
    """Configuration for Redis stream names with validation."""
    
    prefix: str = Field(..., description="Common prefix for all streams")
    sep: str = Field(..., description="Separator character for stream names")
    publish: Dict[str, str] = Field(..., description="Streams for publishing data")
    subscribe: Dict[str, str] = Field(..., description="Streams for subscribing to data")
    
    @field_validator('publish')
    @classmethod
    def validate_publish_prefixes(cls, v: Dict[str, str], info) -> Dict[str, str]:
        """Validate that publish stream names contain the expected prefix."""
        if not v:
            return v
            
        # Get the prefix from the model data
        prefix = info.data.get('prefix', '')
        sep = info.data.get('sep', ':')
        
        if not prefix:
            return v
            
        expected_prefix = f"{prefix}{sep}"
        
        for stream_name, stream_pattern in v.items():
            if not stream_pattern.startswith(expected_prefix):
                raise ValueError(
                    f"Publish stream '{stream_name}' pattern '{stream_pattern}' must start with '{expected_prefix}'"
                )
        
        return v
    
    @field_validator('sep')
    @classmethod
    def validate_separator(cls, v: str) -> str:
        """Validate separator is a single character."""
        if len(v) != 1:
            raise ValueError("Separator must be a single character")
        return v
    
    def get_all_streams(self) -> Dict[str, str]:
        """Get all streams (publish + subscribe) as a single dictionary."""
        return {**self.publish, **self.subscribe}
    
    def get_stream_patterns(self) -> Dict[str, str]:
        """Get all stream patterns with their categories."""
        return {
            **{f"publish.{k}": v for k, v in self.publish.items()},
            **{f"subscribe.{k}": v for k, v in self.subscribe.items()}
        }
