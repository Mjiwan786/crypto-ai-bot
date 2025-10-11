# Configuration System

This directory contains the production-grade configuration system for the crypto AI bot.

## Structure

```
config/
├── settings.yaml              # Global configuration (no secrets)
├── overrides/
│   ├── staging.yaml          # Staging environment overrides
│   └── prod.yaml             # Production environment overrides
├── merge_config.py           # Configuration merger utility
├── requirements.txt          # Dependencies
└── README.md                 # This file
```

## Usage

### Basic Usage

```bash
# Load staging configuration
python config/merge_config.py --env staging

# Load production configuration
python config/merge_config.py --env prod

# Output as JSON
python config/merge_config.py --env staging --format json

# Save to file
python config/merge_config.py --env prod --output config.yaml

# Validate configuration
python config/merge_config.py --env staging --validate
```

### Programmatic Usage

```python
from config.merge_config import load_config

# Load configuration for staging
config = load_config("staging")

# Load configuration for production
config = load_config("prod")
```

## Configuration Files

### settings.yaml
Global configuration file containing:
- Mode settings (PAPER/LIVE)
- Logging configuration
- Risk management parameters
- Strategy allocations
- Redis connection settings
- Kraken API settings
- Monitoring configuration
- Performance settings

### Override Files
Environment-specific overrides that only contain the keys that need to be different from the base configuration.

## Security

- **No secrets in YAML files**: All API keys, tokens, and secrets must be loaded from `.env` files
- **Override support**: Environment-specific configurations without duplicating common settings
- **Deep merging**: Nested configurations are properly merged, not overwritten

## Dependencies

- Python 3.10+
- PyYAML 6.0+

Install with:
```bash
pip install -r config/requirements.txt
```

## Examples

### Staging Environment
- Mode: PAPER
- Logging: DEBUG level
- Risk: Lower position limits
- Monitoring: More frequent health checks

### Production Environment
- Mode: LIVE
- Logging: INFO level
- Risk: Higher position limits
- Monitoring: Standard health check intervals
