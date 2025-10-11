# Crypto AI Bot - Preflight Hard Checks

This directory contains cross-platform preflight checks to verify all deployment prerequisites before touching production.

## Files

- `preflight_hard_checks.py` - Main Python script with all checks
- `preflight_hard_checks.ps1` - Windows PowerShell wrapper
- `preflight_hard_checks.sh` - Linux/macOS bash wrapper

## Usage

### Windows
```powershell
.\scripts\preflight_hard_checks.ps1 -Verbose
```

### Linux/macOS
```bash
bash scripts/preflight_hard_checks.sh --verbose
```

### Direct Python (any platform)
```bash
python scripts/preflight_hard_checks.py --verbose
```

## Checks Performed

### Host Specifications
- ✅ CPU cores (minimum 2)
- ✅ RAM (minimum 4 GB)
- ✅ Disk space (minimum 40 GB free)
  - Windows: Uses `psutil.disk_usage()`
  - Linux: Uses `df -h` command
  - macOS: Uses `statvfs()`

### Time Synchronization
- ✅ Windows: `w32tm /query /status`
- ✅ Linux: `timedatectl | grep 'System clock synchronized'` or `timedatectl show -p NTPSynchronized` or `chronyc tracking`
- ⚠️ macOS: Not supported (warning only)

### Python Runtime
- ✅ Python version 3.10.x
- ✅ Package count from `pip freeze`
- ✅ Critical dependencies: redis, websockets, requests, python-dotenv

### Conda Context
- ✅ Active environment detection
- ⚠️ Warns if not `crypto-bot`

### Logs Path
- ✅ `logs/` directory exists and writable
- ✅ Creates test file and deletes it

### Secrets Hygiene
- ✅ `.env` file exists
- ✅ `.env` permissions (Unix: 600)
- ✅ Scans YAML files for hardcoded secrets
- ✅ Excludes environment variable references (`${VAR}`)

### Redis Connectivity
- ✅ Reads `REDIS_URL` from `.env`
- ✅ SSL validation for `rediss://` URLs
- ✅ PING test
- ✅ Write/read test with temporary key
- ✅ Server info (version, mode)
- ✅ OpenSSL TLS verification (Linux/macOS only): `openssl s_client -connect HOST:PORT -tls1_2 -brief`

### Kraken API
- ✅ REST API: `GET /0/public/SystemStatus`
- ✅ WebSocket: Connect and receive response
- ✅ Latency measurement
- ✅ curl-based REST check (Linux/macOS only): `curl -s https://api.kraken.com/0/public/SystemStatus`

### Configuration Sanity
- ✅ `config/settings.yaml` exists
- ✅ Logging directory configured
- ✅ Strategy allocations sum to ~1.0
- ✅ Redis stream names listed

## Exit Codes

- `0` - All checks passed
- `1` - One or more checks failed

## Dependencies

The script requires these Python packages:
- `psutil` - System information
- `requests` - HTTP client
- `websockets` - WebSocket client
- `redis` - Redis client
- `python-dotenv` - Environment loader
- `pyyaml` - YAML parser

## Platform-Specific Features

### Linux/macOS Additional Checks
- **Disk Usage**: Uses `df -h` command for more detailed disk information
- **Time Sync**: Uses `timedatectl | grep 'System clock synchronized'` for better detection
- **Redis TLS**: Uses `openssl s_client` for TLS certificate verification
- **Kraken REST**: Uses `curl` as additional connectivity test

### Windows
- **Disk Usage**: Uses `psutil.disk_usage()` with fallback to C: drive
- **Time Sync**: Uses `w32tm /query /status` (may require admin privileges)
- **Redis TLS**: Uses Python redis client with SSL validation
- **Kraken REST**: Uses Python requests library

## Notes

- Time sync check may require administrator privileges on Windows
- WebSocket test uses 5-second timeout
- Network timeouts are kept short (5-10 seconds)
- No secrets are printed in output
- ASCII-safe output for Windows compatibility
- Linux/macOS checks require `openssl` and `curl` to be installed for additional verification
