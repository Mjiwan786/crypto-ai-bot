#!/usr/bin/env python3
"""
Crypto AI Bot - Preflight Hard Checks
Cross-platform deployment verification script

Performs comprehensive pre-deployment checks:
- Host specifications (CPU, RAM, disk)
- Time synchronization
- Python runtime and dependencies
- Conda environment
- Logs directory
- Secrets hygiene
- Redis connectivity (with TLS validation)
- Kraken API connectivity (REST + WebSocket)
- Configuration sanity

Exit codes:
- 0: All checks passed
- 1: One or more checks failed
"""

import argparse
import asyncio
import json
import os
import platform
import stat
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

try:
    import requests
except ImportError:
    requests = None

try:
    import websockets
except ImportError:
    websockets = None

try:
    import redis
except ImportError:
    redis = None

try:
    import yaml
except ImportError:
    yaml = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


class PreflightError(Exception):
    """Custom exception for preflight failures"""
    pass


class PreflightChecker:
    """Main preflight checker class"""
    
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.failed_checks = []
        self.warnings = []
        self.start_time = time.time()
        
        # Load environment variables
        if load_dotenv:
            load_dotenv()
    
    def ok(self, message: str) -> None:
        """Print success message"""
        print(f"[OK] {message}")
    
    def fail(self, message: str) -> None:
        """Print failure message and record it"""
        print(f"[FAIL] {message}")
        self.failed_checks.append(message)
    
    def warn(self, message: str) -> None:
        """Print warning message"""
        print(f"[WARN] {message}")
        self.warnings.append(message)
    
    def info(self, message: str) -> None:
        """Print info message (verbose only)"""
        if self.verbose:
            print(f"[INFO] {message}")
    
    def timeit(self, func_name: str):
        """Context manager for timing operations"""
        class TimeIt:
            def __init__(self, checker, name):
                self.checker = checker
                self.name = name
                self.start = None
            
            def __enter__(self):
                self.start = time.time()
                return self
            
            def __exit__(self, exc_type, exc_val, exc_tb):
                if self.start:
                    elapsed = time.time() - self.start
                    self.checker.info(f"{self.name} took {elapsed:.2f}s")
        
        return TimeIt(self, func_name)
    
    def check_host_specs(self) -> None:
        """Check host specifications (CPU, RAM, disk)"""
        print("\n[Preflight] Checking host specifications...")
        
        try:
            if psutil:
                # Use psutil for accurate cross-platform info
                cpu_count = psutil.cpu_count(logical=True)
                memory = psutil.virtual_memory()
                # Use current directory for disk usage check
                try:
                    disk = psutil.disk_usage('.')
                except (OSError, SystemError):
                    # Fallback to C: drive on Windows
                    disk = psutil.disk_usage('C:')
                
                ram_gb = memory.total / (1024**3)
                disk_gb = disk.free / (1024**3)
                
                self.info(f"CPU cores: {cpu_count}")
                self.info(f"RAM: {ram_gb:.1f} GB")
                self.info(f"Disk free: {disk_gb:.1f} GB")
                
                # Check minimum requirements
                if cpu_count < 2:
                    self.fail(f"Host spec: Insufficient CPU cores ({cpu_count} < 2)")
                else:
                    self.ok(f"Host spec: {cpu_count} vCPU, {ram_gb:.1f} GB RAM, {disk_gb:.1f} GB free")
                
                if ram_gb < 4:
                    self.fail(f"Host spec: Insufficient RAM ({ram_gb:.1f} GB < 4 GB)")
                
                if disk_gb < 40:
                    self.fail(f"Host spec: Insufficient disk space ({disk_gb:.1f} GB < 40 GB)")
            else:
                # Fallback to platform utilities
                self.warn("psutil not available, using platform utilities")
                
                # CPU count
                cpu_count = os.cpu_count() or 1
                if cpu_count < 2:
                    self.fail(f"Host spec: Insufficient CPU cores ({cpu_count} < 2)")
                else:
                    self.ok(f"Host spec: {cpu_count} vCPU")
                
                # Memory check (Unix only)
                if platform.system() != "Windows":
                    try:
                        with open('/proc/meminfo', 'r') as f:
                            meminfo = f.read()
                        for line in meminfo.split('\n'):
                            if line.startswith('MemTotal:'):
                                mem_kb = int(line.split()[1])
                                mem_gb = mem_kb / (1024**2)
                                if mem_gb < 4:
                                    self.fail(f"Host spec: Insufficient RAM ({mem_gb:.1f} GB < 4 GB)")
                                else:
                                    self.ok(f"Host spec: {mem_gb:.1f} GB RAM")
                                break
                    except Exception as e:
                        self.warn(f"Could not check RAM: {e}")
                
                # Disk check
                try:
                    if system == "Linux":
                        # Use df -h for Linux
                        result = subprocess.run(
                            ["df", "-h", "."],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            lines = result.stdout.strip().split('\n')
                            if len(lines) > 1:
                                # Parse df output: Filesystem Size Used Avail Use% Mounted_on
                                parts = lines[1].split()
                                if len(parts) >= 4:
                                    avail_str = parts[3]
                                    # Convert to GB (remove 'G' suffix if present)
                                    if avail_str.endswith('G'):
                                        free_gb = float(avail_str[:-1])
                                    elif avail_str.endswith('M'):
                                        free_gb = float(avail_str[:-1]) / 1024
                                    elif avail_str.endswith('K'):
                                        free_gb = float(avail_str[:-1]) / (1024**2)
                                    else:
                                        free_gb = float(avail_str) / (1024**3)
                                    
                                    if free_gb < 40:
                                        self.fail(f"Host spec: Insufficient disk space ({free_gb:.1f} GB < 40 GB)")
                                    else:
                                        self.ok(f"Host spec: {free_gb:.1f} GB free")
                                else:
                                    self.warn("Could not parse df output")
                            else:
                                self.warn("Unexpected df output format")
                        else:
                            self.warn("df command failed")
                    else:
                        # Use statvfs for other Unix systems
                        statvfs = os.statvfs('.')
                        free_gb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
                        if free_gb < 40:
                            self.fail(f"Host spec: Insufficient disk space ({free_gb:.1f} GB < 40 GB)")
                        else:
                            self.ok(f"Host spec: {free_gb:.1f} GB free")
                except Exception as e:
                    self.warn(f"Could not check disk space: {e}")
        
        except Exception as e:
            self.fail(f"Host spec: Failed to check system specs: {e}")
    
    def check_time_sync(self) -> None:
        """Check time synchronization"""
        print("\n[Preflight] Checking time synchronization...")
        
        try:
            system = platform.system()
            
            if system == "Windows":
                # Windows time sync check
                try:
                    result = subprocess.run(
                        ["w32tm", "/query", "/status"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    
                    if result.returncode == 0:
                        output = result.stdout.lower()
                        if "synchronized" in output or "source: time.windows.com" in output:
                            self.ok("Time sync: NTP synchronized")
                        else:
                            self.warn("Time sync: Not synchronized")
                    else:
                        self.warn(f"Time sync: w32tm query failed (may need admin privileges): {result.stderr}")
                
                except subprocess.TimeoutExpired:
                    self.fail("Time sync: w32tm query timeout")
                except FileNotFoundError:
                    self.warn("Time sync: w32tm not found, cannot verify")
            
            elif system == "Linux":
                # Linux time sync check
                try:
                    # Try timedatectl status first (more detailed)
                    result = subprocess.run(
                        ["timedatectl"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    
                    if result.returncode == 0:
                        if "System clock synchronized: yes" in result.stdout:
                            self.ok("Time sync: NTP synchronized")
                        else:
                            self.warn("Time sync: Not synchronized")
                    else:
                        # Fallback to timedatectl show
                        result = subprocess.run(
                            ["timedatectl", "show", "-p", "NTPSynchronized"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        
                        if result.returncode == 0:
                            if "yes" in result.stdout.lower():
                                self.ok("Time sync: NTP synchronized")
                            else:
                                self.warn("Time sync: Not synchronized")
                        else:
                            # Fallback to chronyc
                            try:
                                result = subprocess.run(
                                    ["chronyc", "tracking"],
                                    capture_output=True,
                                    text=True,
                                    timeout=5
                                )
                                if result.returncode == 0 and "reference time" in result.stdout:
                                    self.ok("Time sync: Chrony tracking active")
                                else:
                                    self.warn("Time sync: Cannot verify synchronization")
                            except FileNotFoundError:
                                self.warn("Time sync: No time sync tools available")
                
                except subprocess.TimeoutExpired:
                    self.warn("Time sync: Timeout checking synchronization")
                except FileNotFoundError:
                    self.warn("Time sync: timedatectl not found")
            
            else:
                # macOS or other Unix
                self.warn("Time sync: Platform not supported for time sync check")
        
        except Exception as e:
            self.fail(f"Time sync: Failed to check: {e}")
    
    def check_python_runtime(self) -> None:
        """Check Python runtime and dependencies"""
        print("\n[Preflight] Checking Python runtime...")
        
        # Check Python version
        if sys.version_info[:2] != (3, 10):
            self.fail(f"Python runtime: Expected 3.10.x, got {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        else:
            self.ok(f"Python runtime: {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
        
        # Check pip freeze count
        try:
            result = subprocess.run(
                [sys.executable, "-m", "pip", "freeze"],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                package_count = len([line for line in result.stdout.split('\n') if line.strip()])
                self.info(f"Installed packages: {package_count}")
            else:
                self.warn("Could not count installed packages")
        
        except Exception as e:
            self.warn(f"Could not check pip freeze: {e}")
        
        # Check critical dependencies
        critical_deps = {
            'redis': 'Redis client',
            'websockets': 'WebSocket client',
            'requests': 'HTTP client',
            'dotenv': 'Environment loader'
        }
        
        for module, description in critical_deps.items():
            try:
                __import__(module)
                self.ok(f"Python deps: {description} available")
            except ImportError:
                self.fail(f"Python deps: {description} missing")
    
    def check_conda_context(self) -> None:
        """Check conda environment context"""
        print("\n[Preflight] Checking conda context...")
        
        conda_env = os.environ.get('CONDA_DEFAULT_ENV')
        if conda_env:
            if conda_env == 'crypto-bot':
                self.ok(f"Conda context: Active env is {conda_env}")
            else:
                self.warn(f"Conda context: Active env is {conda_env}, expected crypto-bot")
        else:
            self.warn("Conda context: No active conda environment detected")
    
    def check_logs_path(self) -> None:
        """Check logs directory exists and is writable"""
        print("\n[Preflight] Checking logs path...")
        
        logs_dir = Path("logs")
        
        try:
            # Create logs directory if it doesn't exist
            logs_dir.mkdir(exist_ok=True)
            
            # Test write access
            test_file = logs_dir / ".preflight_touch"
            test_file.write_text("test")
            test_file.unlink()
            
            self.ok("Logs path: Directory exists and is writable")
        
        except Exception as e:
            self.fail(f"Logs path: Cannot create/write to logs directory: {e}")
    
    def check_secrets_hygiene(self) -> None:
        """Check for secrets in configuration files"""
        print("\n[Preflight] Checking secrets hygiene...")
        
        # Check .env exists
        env_file = Path(".env")
        if not env_file.exists():
            self.fail("Secrets hygiene: .env file missing")
            return
        else:
            self.ok("Secrets hygiene: .env file exists")
        
        # Check .env permissions on Unix
        if platform.system() != "Windows":
            try:
                stat_info = env_file.stat()
                mode = stat_info.st_mode
                if (mode & stat.S_IRWXG) or (mode & stat.S_IRWXO):
                    self.warn("Secrets hygiene: .env permissions too permissive (should be 600)")
                else:
                    self.ok("Secrets hygiene: .env permissions secure")
            except Exception as e:
                self.warn(f"Secrets hygiene: Could not check .env permissions: {e}")
        
        # Scan YAML files for potential secrets (exclude env var references)
        config_dir = Path("config")
        if config_dir.exists():
            yaml_files = list(config_dir.rglob("*.yaml")) + list(config_dir.rglob("*.yml"))
            secrets_found = False
            
            for yaml_file in yaml_files:
                try:
                    with open(yaml_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    for i, line in enumerate(content.split('\n'), 1):
                        line_stripped = line.strip()
                        
                        # Skip comments and empty lines
                        if line_stripped.startswith('#') or not line_stripped:
                            continue
                        
                        # Check for hardcoded secrets (not env var references)
                        if (': ' in line_stripped and 
                            not line_stripped.endswith('null') and
                            not line_stripped.endswith('""') and
                            not line_stripped.endswith("''") and
                            '${' not in line_stripped and
                            not line_stripped.endswith(':')):
                            
                            # Check for secret-like patterns
                            secret_keywords = ['api_key', 'api_secret', 'secret', 'token', 'password']
                            for keyword in secret_keywords:
                                if keyword in line_stripped.lower():
                                    # Extract the value part
                                    if ': ' in line_stripped:
                                        key, value = line_stripped.split(': ', 1)
                                        value = value.strip()
                                        
                                        # Skip if it's clearly an env var reference
                                        if value.startswith('${') and value.endswith('}'):
                                            continue
                                        
                                        # Skip if it's null, empty, or just a placeholder
                                        if value in ['null', '""', "''", 'your_key_here', 'your_secret_here']:
                                            continue
                                        
                                        # Skip if it's a configuration flag (like "mask_api_keys: true")
                                        if value in ['true', 'false', 'yes', 'no']:
                                            continue
                                        
                                        # Skip if it's a number (like "max_tokens: 4000")
                                        if value.isdigit():
                                            continue
                                        
                                        # Skip if it's a string that looks like a config value
                                        if value.startswith('"') and value.endswith('"'):
                                            continue
                                        
                                        # This looks like a hardcoded secret
                                        self.fail(f"Secrets hygiene: Potential secret in {yaml_file}:{i}: {line_stripped}")
                                        secrets_found = True
                                        break
                
                except Exception as e:
                    self.warn(f"Secrets hygiene: Could not scan {yaml_file}: {e}")
            
            if not secrets_found:
                self.ok("Secrets hygiene: No hardcoded secrets found in config files")
        else:
            self.ok("Secrets hygiene: No config directory found")
    
    def check_redis_connectivity(self) -> None:
        """Check Redis connectivity with TLS validation"""
        print("\n[Preflight] Checking Redis connectivity...")
        
        if not redis:
            self.fail("Redis connectivity: redis module not available")
            return
        
        redis_url = os.environ.get('REDIS_URL')
        if not redis_url:
            self.fail("Redis connectivity: REDIS_URL not set")
            return
        
        try:
            # Parse Redis URL
            parsed = urllib.parse.urlparse(redis_url)
            host = parsed.hostname or 'localhost'
            port = parsed.port or 6379
            password = parsed.password
            ssl_enabled = parsed.scheme == 'rediss'
            
            self.info(f"Redis host: {host}:{port}")
            self.info(f"Redis SSL: {ssl_enabled}")
            
            # Create Redis client
            client_kwargs = {
                'host': host,
                'port': port,
                'decode_responses': True,
                'socket_timeout': 10,
                'socket_connect_timeout': 10
            }
            
            if password:
                client_kwargs['password'] = password
            
            if ssl_enabled:
                client_kwargs['ssl'] = True
                client_kwargs['ssl_cert_reqs'] = 'required'
                client_kwargs['ssl_check_hostname'] = True
            
            with redis.Redis(**client_kwargs) as client:
                # Test connection
                with self.timeit("Redis PING"):
                    pong = client.ping()
                    if pong:
                        self.ok("Redis connectivity: PING successful")
                    else:
                        self.fail("Redis connectivity: PING failed")
                        return
                
                # Test write/read
                test_key = "preflight_test_key"
                test_value = f"test_{int(time.time())}"
                
                with self.timeit("Redis write/read"):
                    client.set(test_key, test_value, ex=60)
                    retrieved = client.get(test_key)
                    client.delete(test_key)
                
                if retrieved == test_value:
                    self.ok("Redis connectivity: Write/read test successful")
                else:
                    self.fail("Redis connectivity: Write/read test failed")
                
                # Get server info
                try:
                    info = client.info()
                    version = info.get('redis_version', 'unknown')
                    mode = info.get('redis_mode', 'unknown')
                    self.info(f"Redis server: {version} ({mode})")
                except Exception as e:
                    self.warn(f"Redis connectivity: Could not get server info: {e}")
                
                # Additional TLS check using OpenSSL (Linux/macOS only)
                if ssl_enabled and platform.system() in ["Linux", "Darwin"]:
                    self.check_redis_tls_with_openssl(host, port)
        
        except redis.ConnectionError as e:
            self.fail(f"Redis connectivity: Connection failed: {e}")
        except redis.AuthenticationError as e:
            self.fail(f"Redis connectivity: Authentication failed: {e}")
        except Exception as e:
            self.fail(f"Redis connectivity: Error: {e}")
    
    def check_redis_tls_with_openssl(self, host: str, port: int) -> None:
        """Check Redis TLS connectivity using OpenSSL"""
        try:
            with self.timeit("Redis TLS OpenSSL"):
                result = subprocess.run(
                    ["openssl", "s_client", "-connect", f"{host}:{port}", "-tls1_2", "-brief"],
                    input="",  # Send empty input to close connection
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    # Check for successful TLS handshake
                    output = result.stdout.lower()
                    if "verify return code: 0" in output or "verify ok" in output:
                        self.ok("Redis TLS: OpenSSL verification successful")
                    else:
                        self.warn("Redis TLS: OpenSSL verification had issues")
                else:
                    self.warn(f"Redis TLS: OpenSSL check failed: {result.stderr}")
        
        except FileNotFoundError:
            self.warn("Redis TLS: OpenSSL not available for TLS verification")
        except subprocess.TimeoutExpired:
            self.warn("Redis TLS: OpenSSL check timeout")
        except Exception as e:
            self.warn(f"Redis TLS: OpenSSL check error: {e}")
    
    def check_kraken_rest(self) -> None:
        """Check Kraken REST API connectivity"""
        print("\n[Preflight] Checking Kraken REST API...")
        
        if not requests:
            self.fail("Kraken REST: requests module not available")
            return
        
        kraken_url = os.environ.get('KRAKEN_API_URL', 'https://api.kraken.com')
        endpoint = f"{kraken_url}/0/public/SystemStatus"
        
        try:
            with self.timeit("Kraken REST"):
                response = requests.get(endpoint, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                status = data.get('result', {}).get('status', 'unknown')
                latency = response.elapsed.total_seconds() * 1000
                
                if status == 'online':
                    self.ok(f"Kraken REST: Online (latency: {latency:.0f}ms)")
                else:
                    self.fail(f"Kraken REST: Status is {status}")
            else:
                self.fail(f"Kraken REST: HTTP {response.status_code}")
        
        except requests.Timeout:
            self.fail("Kraken REST: Request timeout")
        except requests.ConnectionError as e:
            self.fail(f"Kraken REST: Connection error: {e}")
        except Exception as e:
            self.fail(f"Kraken REST: Error: {e}")
        
        # Additional curl-based check (Linux/macOS only)
        if platform.system() in ["Linux", "Darwin"]:
            self.check_kraken_rest_with_curl(kraken_url)
    
    def check_kraken_rest_with_curl(self, kraken_url: str) -> None:
        """Check Kraken REST API using curl (Linux/macOS only)"""
        try:
            with self.timeit("Kraken REST curl"):
                result = subprocess.run(
                    ["curl", "-s", f"{kraken_url}/0/public/SystemStatus"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    try:
                        data = json.loads(result.stdout)
                        status = data.get('result', {}).get('status', 'unknown')
                        if status == 'online':
                            self.ok("Kraken REST: curl check successful")
                        else:
                            self.warn(f"Kraken REST: curl check - status is {status}")
                    except json.JSONDecodeError:
                        self.warn("Kraken REST: curl check - invalid JSON response")
                else:
                    self.warn(f"Kraken REST: curl check failed: {result.stderr}")
        
        except FileNotFoundError:
            self.warn("Kraken REST: curl not available for additional check")
        except subprocess.TimeoutExpired:
            self.warn("Kraken REST: curl check timeout")
        except Exception as e:
            self.warn(f"Kraken REST: curl check error: {e}")
    
    async def check_kraken_websocket(self) -> None:
        """Check Kraken WebSocket connectivity"""
        print("\n[Preflight] Checking Kraken WebSocket...")
        
        if not websockets:
            self.fail("Kraken WebSocket: websockets module not available")
            return
        
        ws_url = "wss://ws.kraken.com"
        
        try:
            with self.timeit("Kraken WebSocket"):
                async with websockets.connect(ws_url) as websocket:
                    # Send ping
                    ping_msg = {"event": "ping"}
                    await websocket.send(json.dumps(ping_msg))
                    
                    # Wait for response
                    response = await asyncio.wait_for(websocket.recv(), timeout=5)
                    data = json.loads(response)
                    
                    if data.get('event') in ['pong', 'heartbeat', 'systemStatus']:
                        self.ok("Kraken WebSocket: Connection successful")
                    else:
                        self.fail(f"Kraken WebSocket: Unexpected response: {data}")
        
        except asyncio.TimeoutError:
            self.fail("Kraken WebSocket: Connection timeout")
        except websockets.exceptions.ConnectionClosed as e:
            self.fail(f"Kraken WebSocket: Connection closed: {e}")
        except Exception as e:
            self.fail(f"Kraken WebSocket: Error: {e}")
    
    def check_config_sanity(self) -> None:
        """Check configuration sanity"""
        print("\n[Preflight] Checking configuration sanity...")
        
        if not yaml:
            self.fail("Config sanity: PyYAML module not available")
            return
        
        config_file = Path("config/settings.yaml")
        if not config_file.exists():
            self.fail("Config sanity: config/settings.yaml not found")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            
            # Check logging directory
            log_dir = config.get('logging', {}).get('dir', 'logs')
            log_path = Path(log_dir)
            
            if log_path.exists() and log_path.is_dir():
                self.ok("Config sanity: Logging directory exists")
            else:
                self.warn(f"Config sanity: Logging directory {log_dir} does not exist")
            
            # Check strategy allocations
            allocations = config.get('strategies', {}).get('allocations', {})
            if allocations:
                total = sum(allocations.values())
                if abs(total - 1.0) <= 0.01:
                    self.ok(f"Config sanity: Strategy allocations sum to {total:.3f}")
                else:
                    self.warn(f"Config sanity: Strategy allocations sum to {total:.3f}, expected ~1.0")
            
            # Print Redis stream names
            redis_config = config.get('redis', {})
            streams = redis_config.get('streams', {})
            if streams:
                self.info("Redis streams configured:")
                for name, stream_name in streams.items():
                    self.info(f"  {name}: {stream_name}")
                self.ok("Config sanity: Redis streams configured")
            else:
                self.warn("Config sanity: No Redis streams configured")
        
        except Exception as e:
            self.fail(f"Config sanity: Error loading config: {e}")
    
    async def run_all_checks(self) -> bool:
        """Run all preflight checks"""
        print("[Preflight] Starting comprehensive deployment checks...")
        print(f"[Preflight] Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro} on {platform.system()}")
        
        # Run synchronous checks
        self.check_host_specs()
        self.check_time_sync()
        self.check_python_runtime()
        self.check_conda_context()
        self.check_logs_path()
        self.check_secrets_hygiene()
        self.check_redis_connectivity()
        self.check_kraken_rest()
        self.check_config_sanity()
        
        # Run async checks
        await self.check_kraken_websocket()
        
        # Summary
        elapsed = time.time() - self.start_time
        print(f"\n[Preflight] Completed in {elapsed:.2f}s")
        
        if self.failed_checks:
            print(f"\n[FAIL] {len(self.failed_checks)} checks failed:")
            for check in self.failed_checks:
                print(f"   - {check}")
            return False
        else:
            print("\n[OK] All checks passed!")
            if self.warnings:
                print(f"[WARN] {len(self.warnings)} warnings (non-blocking):")
                for warning in self.warnings:
                    print(f"   - {warning}")
            return True


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Crypto AI Bot Preflight Checks")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    args = parser.parse_args()
    
    checker = PreflightChecker(verbose=args.verbose)
    success = await checker.run_all_checks()
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
