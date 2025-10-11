#!/usr/bin/env python3
"""
Configuration merger for crypto AI bot.

Deep merges base settings.yaml with environment-specific overrides.
Supports staging and production environments.
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, Union

try:
    import yaml
except ImportError:
    print("Error: PyYAML is required. Install with: pip install PyYAML")
    sys.exit(1)


def deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """
    Deep merge two dictionaries.
    
    Args:
        base: Base dictionary
        override: Override dictionary
        
    Returns:
        Merged dictionary with override values taking precedence
    """
    result = base.copy()
    
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


def load_yaml_file(file_path: Path) -> Dict[str, Any]:
    """
    Load YAML file and return as dictionary.
    
    Args:
        file_path: Path to YAML file
        
    Returns:
        Dictionary representation of YAML content
        
    Raises:
        FileNotFoundError: If file doesn't exist
        yaml.YAMLError: If YAML is invalid
    """
    if not file_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_config(env: str = "staging") -> Dict[str, Any]:
    """
    Load and merge configuration for specified environment.
    
    Args:
        env: Environment name (staging, prod, etc.)
        
    Returns:
        Merged configuration dictionary
        
    Raises:
        FileNotFoundError: If required config files don't exist
        yaml.YAMLError: If YAML files are invalid
    """
    # Get the directory containing this script
    config_dir = Path(__file__).parent
    
    # Load base settings
    base_config_path = config_dir / "settings.yaml"
    base_config = load_yaml_file(base_config_path)
    
    # Load environment-specific override
    override_path = config_dir / "overrides" / f"{env}.yaml"
    
    if override_path.exists():
        override_config = load_yaml_file(override_path)
        merged_config = deep_merge(base_config, override_config)
    else:
        print(f"Warning: No override file found for environment '{env}' at {override_path}")
        merged_config = base_config
    
    return merged_config


def print_config(config: Dict[str, Any], output_format: str = "yaml") -> None:
    """
    Print configuration in specified format.
    
    Args:
        config: Configuration dictionary
        output_format: Output format ("yaml" or "json")
    """
    if output_format.lower() == "yaml":
        print(yaml.dump(config, default_flow_style=False, sort_keys=False))
    elif output_format.lower() == "json":
        import json
        print(json.dumps(config, indent=2, sort_keys=False))
    else:
        raise ValueError(f"Unsupported output format: {output_format}")


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Merge configuration files for crypto AI bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python config/merge_config.py --env staging
  python config/merge_config.py --env prod --format json
  python config/merge_config.py --env staging --output config.yaml
        """
    )
    
    parser.add_argument(
        "--env",
        default="staging",
        choices=["staging", "prod", "production"],
        help="Environment to load configuration for (default: staging)"
    )
    
    parser.add_argument(
        "--format",
        default="yaml",
        choices=["yaml", "json"],
        help="Output format (default: yaml)"
    )
    
    parser.add_argument(
        "--output",
        help="Output file path (default: stdout)"
    )
    
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate configuration without printing"
    )
    
    args = parser.parse_args()
    
    try:
        # Normalize environment name
        env = "prod" if args.env == "production" else args.env
        
        # Load configuration
        config = load_config(env)
        
        if args.validate:
            print(f"Configuration for environment '{env}' is valid")
            return
        
        # Output configuration
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                if args.format.lower() == "yaml":
                    yaml.dump(config, f, default_flow_style=False, sort_keys=False)
                else:
                    import json
                    json.dump(config, f, indent=2, sort_keys=False)
            
            print(f"Configuration written to {output_path}")
        else:
            print_config(config, args.format)
            
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing YAML: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
