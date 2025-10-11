#!/usr/bin/env python3
"""
Staging Pipeline Supervisor for Crypto AI Bot

Orchestrates the startup sequence and health verification for staging environment:
1. Market Data Ingestors (WebSocket) → publish to md:*
2. Signal/Strategy Agents → read md:*, publish to signals:staging  
3. Execution Agent (PAPER) → consumes signals:staging, NO live orders

Usage:
    python scripts/run_staging.py --env .env.staging --timeout 30 --include-exec --verbose

Environment Requirements:
    - ENVIRONMENT=staging
    - mode=PAPER (from config)
    - Redis connection available
    - All required API keys configured
"""

import argparse
import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

import redis.asyncio as redis
import yaml
from dotenv import load_dotenv

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Import config merger
from config.merge_config import load_config


class ProcessStatus(Enum):
    """Process status enumeration"""
    PENDING = "pending"
    STARTING = "starting"
    READY = "ready"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class ProcessInfo:
    """Information about a managed process"""
    name: str
    cmd: List[str]
    env: Dict[str, str]
    ready_regex: str
    log_file: str
    status: ProcessStatus = ProcessStatus.PENDING
    process: Optional[subprocess.Popen] = None
    start_time: Optional[float] = None
    ready_time: Optional[float] = None
    last_heartbeat: Optional[float] = None


class StagingSupervisor:
    """Main supervisor class for staging pipeline"""
    
    def __init__(self, env_file: str, timeout: int, include_exec: bool, verbose: bool):
        self.env_file = Path(env_file)
        self.timeout = timeout
        self.include_exec = include_exec
        self.verbose = verbose
        
        # Setup logging
        self.logger = self._setup_logging()
        
        # Process tracking
        self.processes: Dict[str, ProcessInfo] = {}
        self.redis_client: Optional[redis.Redis] = None
        self.config: Optional[Dict[str, Any]] = None
        
        # Control flags
        self.running = False
        self.shutdown_requested = False
        
        # Health check intervals
        self.health_check_interval = 30  # seconds
        self.last_health_check = 0
        
        # Install signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging configuration"""
        logger = logging.getLogger("staging_supervisor")
        logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        
        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        
        logger.addHandler(console_handler)
        return logger
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_requested = True
        self.running = False
    
    async def initialize(self) -> bool:
        """Initialize the supervisor and validate environment"""
        try:
            # Load environment
            if not self.env_file.exists():
                self.logger.error(f"Environment file not found: {self.env_file}")
                return False
            
            load_dotenv(self.env_file)
            
            # Validate environment
            if os.getenv("ENVIRONMENT") != "staging":
                self.logger.error("ENVIRONMENT must be set to 'staging'")
                return False
            
            # Load configuration
            self.config = load_config("staging")
            
            # Validate mode is PAPER
            mode = self.config.get("mode", {}).get("bot_mode", "UNKNOWN")
            if mode != "PAPER":
                self.logger.error(f"Mode must be PAPER for staging, got: {mode}")
                return False
            
            # Initialize Redis connection
            redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
            ssl_enabled = os.getenv("REDIS_SSL_ENABLED", "false").lower() == "true"
            
            # For Redis Cloud with TLS, use rediss:// protocol
            self.redis_client = redis.from_url(redis_url, decode_responses=True)
            
            # Test Redis connection
            await self.redis_client.ping()
            self.logger.info("✅ Redis connection established")
            
            # Load process manifests
            await self._load_process_manifests()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Initialization failed: {e}")
            return False
    
    async def _load_process_manifests(self):
        """Load process manifests from JSON files"""
        manifest_dir = PROJECT_ROOT / "procfiles"
        
        # Load ingestors
        ingestors_file = manifest_dir / "staging_ingestors.json"
        if ingestors_file.exists():
            with open(ingestors_file) as f:
                data = json.load(f)
                for proc_data in data.get("procs", []):
                    proc = ProcessInfo(
                        name=proc_data["name"],
                        cmd=proc_data["cmd"],
                        env=proc_data.get("env", {}),
                        ready_regex=proc_data["ready_regex"],
                        log_file=proc_data["log"]
                    )
                    self.processes[proc.name] = proc
        
        # Load strategies
        strategies_file = manifest_dir / "staging_strategies.json"
        if strategies_file.exists():
            with open(strategies_file) as f:
                data = json.load(f)
                for proc_data in data.get("procs", []):
                    proc = ProcessInfo(
                        name=proc_data["name"],
                        cmd=proc_data["cmd"],
                        env=proc_data.get("env", {}),
                        ready_regex=proc_data["ready_regex"],
                        log_file=proc_data["log"]
                    )
                    self.processes[proc.name] = proc
        
        # Load execution (if requested)
        if self.include_exec:
            execution_file = manifest_dir / "staging_execution.json"
            if execution_file.exists():
                with open(execution_file) as f:
                    data = json.load(f)
                    for proc_data in data.get("procs", []):
                        proc = ProcessInfo(
                            name=proc_data["name"],
                            cmd=proc_data["cmd"],
                            env=proc_data.get("env", {}),
                            ready_regex=proc_data["ready_regex"],
                            log_file=proc_data["log"]
                        )
                        self.processes[proc.name] = proc
        
        self.logger.info(f"Loaded {len(self.processes)} process definitions")
    
    async def start_stage(self, stage_name: str, process_names: List[str]) -> bool:
        """Start a stage of processes and wait for readiness"""
        self.logger.info(f"🚀 Starting {stage_name} stage...")
        
        # Start processes
        for proc_name in process_names:
            if proc_name not in self.processes:
                self.logger.error(f"Process {proc_name} not found in manifests")
                return False
            
            proc = self.processes[proc_name]
            if not await self._start_process(proc):
                return False
        
        # Wait for readiness
        ready_count = 0
        start_time = time.time()
        
        while time.time() - start_time < self.timeout:
            for proc_name in process_names:
                proc = self.processes[proc_name]
                if proc.status == ProcessStatus.READY:
                    continue
                elif proc.status == ProcessStatus.FAILED:
                    self.logger.error(f"❌ Process {proc_name} failed to start")
                    return False
                elif await self._check_process_ready(proc):
                    proc.status = ProcessStatus.READY
                    proc.ready_time = time.time()
                    ready_count += 1
                    self.logger.info(f"✅ {proc_name} ready")
            
            if ready_count == len(process_names):
                self.logger.info(f"✅ {stage_name} stage ready ({ready_count}/{len(process_names)})")
                return True
            
            await asyncio.sleep(1)
        
        self.logger.error(f"❌ {stage_name} stage timeout after {self.timeout}s")
        return False
    
    async def _start_process(self, proc: ProcessInfo) -> bool:
        """Start a single process"""
        try:
            # Prepare environment
            env = os.environ.copy()
            env.update(proc.env)
            env["ENVIRONMENT"] = "staging"
            env["LOG_LEVEL"] = "INFO"
            
            # Ensure log directory exists
            log_path = Path(proc.log_file)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Open log file
            log_file = open(log_path, "w")
            
            # Start process
            if sys.platform == "win32":
                # Windows: use creationflags
                proc.process = subprocess.Popen(
                    proc.cmd,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )
            else:
                # POSIX: use preexec_fn
                proc.process = subprocess.Popen(
                    proc.cmd,
                    env=env,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid
                )
            
            proc.status = ProcessStatus.STARTING
            proc.start_time = time.time()
            
            self.logger.info(f"Started {proc.name} (PID: {proc.process.pid})")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start {proc.name}: {e}")
            proc.status = ProcessStatus.FAILED
            return False
    
    async def _check_process_ready(self, proc: ProcessInfo) -> bool:
        """Check if a process is ready based on its log output"""
        if proc.status != ProcessStatus.STARTING:
            return False
        
        try:
            # Check if process is still running
            if proc.process and proc.process.poll() is not None:
                proc.status = ProcessStatus.FAILED
                return False
            
            # Check log file for ready pattern
            if Path(proc.log_file).exists():
                with open(proc.log_file, "r") as f:
                    content = f.read()
                    if re.search(proc.ready_regex, content, re.IGNORECASE):
                        return True
            
            # Check Redis readiness key
            if self.redis_client:
                ready_key = f"md:ready:{proc.name}"
                ready_value = await self.redis_client.get(ready_key)
                if ready_value == "true":
                    return True
            
            return False
            
        except Exception as e:
            self.logger.debug(f"Error checking readiness for {proc.name}: {e}")
            return False
    
    async def verify_ingestors_health(self) -> bool:
        """Verify ingestors are publishing data to Redis streams"""
        try:
            # Check for recent data in md:* streams
            streams_to_check = ["md:orderbook", "md:trades", "md:spread"]
            current_time = int(time.time() * 1000)
            cutoff_time = current_time - 30000  # 30 seconds ago
            
            for stream in streams_to_check:
                # Get stream info
                info = await self.redis_client.xinfo_stream(stream)
                if not info:
                    self.logger.warning(f"Stream {stream} not found")
                    continue
                
                last_id = info.get("last-entry", {}).get("id", "0-0")
                if last_id != "0-0":
                    # Parse timestamp from stream ID
                    timestamp = int(last_id.split("-")[0])
                    if timestamp > cutoff_time:
                        self.logger.info(f"✅ {stream} has recent data (last: {current_time - timestamp}ms ago)")
                    else:
                        self.logger.warning(f"⚠️ {stream} data is stale (last: {current_time - timestamp}ms ago)")
                else:
                    self.logger.warning(f"⚠️ {stream} is empty")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False
    
    async def verify_strategies_health(self) -> bool:
        """Verify strategies are consuming and producing data"""
        try:
            # Check signals:staging stream
            stream = "signals:staging"
            info = await self.redis_client.xinfo_stream(stream)
            
            if info:
                last_id = info.get("last-entry", {}).get("id", "0-0")
                if last_id != "0-0":
                    timestamp = int(last_id.split("-")[0])
                    current_time = int(time.time() * 1000)
                    age_ms = current_time - timestamp
                    self.logger.info(f"✅ {stream} has recent signals (last: {age_ms}ms ago)")
                    return True
                else:
                    self.logger.warning(f"⚠️ {stream} is empty")
                    return False
            else:
                self.logger.warning(f"⚠️ {stream} not found")
                return False
                
        except Exception as e:
            self.logger.error(f"Strategy health check failed: {e}")
            return False
    
    async def verify_execution_health(self) -> bool:
        """Verify execution agent is working in paper mode"""
        try:
            # Check exec:paper:confirms stream
            stream = "exec:paper:confirms"
            info = await self.redis_client.xinfo_stream(stream)
            
            if info:
                last_id = info.get("last-entry", {}).get("id", "0-0")
                if last_id != "0-0":
                    timestamp = int(last_id.split("-")[0])
                    current_time = int(time.time() * 1000)
                    age_ms = current_time - timestamp
                    self.logger.info(f"✅ {stream} has recent confirmations (last: {age_ms}ms ago)")
                    return True
                else:
                    self.logger.warning(f"⚠️ {stream} is empty")
                    return False
            else:
                self.logger.warning(f"⚠️ {stream} not found")
                return False
                
        except Exception as e:
            self.logger.error(f"Execution health check failed: {e}")
            return False
    
    async def run_health_checks(self) -> bool:
        """Run periodic health checks"""
        current_time = time.time()
        if current_time - self.last_health_check < self.health_check_interval:
            return True
        
        self.last_health_check = current_time
        
        # Check ingestors
        if not await self.verify_ingestors_health():
            return False
        
        # Check strategies
        if not await self.verify_strategies_health():
            return False
        
        # Check execution (if enabled)
        if self.include_exec and not await self.verify_execution_health():
            return False
        
        return True
    
    async def run(self) -> int:
        """Main supervisor loop"""
        try:
            # Initialize
            if not await self.initialize():
                return 1
            
            self.running = True
            
            # Stage 1: Start Ingestors
            ingestor_processes = [name for name in self.processes.keys() if "ingestor" in name]
            if not await self.start_stage("Ingestors", ingestor_processes):
                return 1
            
            # Stage 2: Start Strategies
            strategy_processes = [name for name in self.processes.keys() if "strategy" in name or "signal" in name]
            if not await self.start_stage("Strategies", strategy_processes):
                return 1
            
            # Stage 3: Start Execution (if requested)
            if self.include_exec:
                execution_processes = [name for name in self.processes.keys() if "execution" in name or "exec" in name]
                if not await self.start_stage("Execution", execution_processes):
                    return 1
            
            # Print success summary
            self.logger.info("=" * 60)
            self.logger.info("🎉 STAGING PIPELINE UP (PAPER)")
            self.logger.info("=" * 60)
            
            # Main monitoring loop
            while self.running and not self.shutdown_requested:
                try:
                    # Check if any process died
                    for proc in self.processes.values():
                        if proc.process and proc.process.poll() is not None:
                            self.logger.error(f"❌ Process {proc.name} died unexpectedly")
                            return 1
                    
                    # Run health checks
                    if not await self.run_health_checks():
                        self.logger.warning("⚠️ Health check failed, continuing...")
                    
                    await asyncio.sleep(5)
                    
                except KeyboardInterrupt:
                    self.logger.info("Received interrupt, shutting down...")
                    break
            
            return 0
            
        except Exception as e:
            self.logger.error(f"Supervisor error: {e}")
            return 1
        
        finally:
            await self.cleanup()
    
    async def cleanup(self):
        """Cleanup resources and stop processes"""
        self.logger.info("Cleaning up...")
        
        # Stop all processes
        for proc in self.processes.values():
            if proc.process and proc.process.poll() is None:
                self.logger.info(f"Stopping {proc.name}...")
                try:
                    if sys.platform == "win32":
                        proc.process.terminate()
                    else:
                        os.killpg(os.getpgid(proc.process.pid), signal.SIGTERM)
                    
                    # Wait for graceful shutdown
                    try:
                        proc.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.logger.warning(f"Force killing {proc.name}")
                        proc.process.kill()
                        
                except Exception as e:
                    self.logger.error(f"Error stopping {proc.name}: {e}")
        
        # Close Redis connection
        if self.redis_client:
            await self.redis_client.close()


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Staging Pipeline Supervisor for Crypto AI Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_staging.py --env .env.staging
  python scripts/run_staging.py --env .env.staging --include-exec --verbose
  python scripts/run_staging.py --env .env.staging --timeout 60
        """
    )
    
    parser.add_argument(
        "--env",
        default=".env.staging",
        help="Environment file path (default: .env.staging)"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Readiness timeout in seconds (default: 30)"
    )
    
    parser.add_argument(
        "--include-exec",
        action="store_true",
        help="Include execution agent in paper mode"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    
    args = parser.parse_args()
    
    # Create and run supervisor
    supervisor = StagingSupervisor(
        env_file=args.env,
        timeout=args.timeout,
        include_exec=args.include_exec,
        verbose=args.verbose
    )
    
    return await supervisor.run()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
