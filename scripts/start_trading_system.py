#!/usr/bin/env python3
"""
Startup script for the complete trading system.

This script provides a comprehensive startup process that:
1. Validates environment and dependencies
2. Loads and validates configuration
3. Starts the master orchestrator
4. Provides health monitoring
5. Handles graceful shutdown
"""

import asyncio
import logging
import os
import sys
import signal
import time
from pathlib import Path
from typing import Dict, Any, Optional
import argparse

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import system components
from config.unified_config_loader import get_config_loader, SystemConfig
from orchestration.master_orchestrator import MasterOrchestrator
from main import setup_logging, health_check

class TradingSystemManager:
    """Manages the complete trading system lifecycle"""
    
    def __init__(self, config_path: str = "config/settings.yaml"):
        self.config_path = config_path
        self.logger = logging.getLogger("TradingSystemManager")
        self.orchestrator: Optional[MasterOrchestrator] = None
        self.running = False
        
    async def validate_environment(self) -> bool:
        """Validate environment and dependencies"""
        self.logger.info("🔍 Validating environment...")
        
        issues = []
        
        # Check Python version
        if sys.version_info < (3, 8):
            issues.append("Python 3.8+ required")
        
        # Check required environment variables
        required_env_vars = ['REDIS_URL', 'KRAKEN_API_KEY', 'KRAKEN_API_SECRET']
        for var in required_env_vars:
            if not os.getenv(var):
                issues.append(f"Environment variable {var} not set")
        
        # Check configuration file
        if not Path(self.config_path).exists():
            issues.append(f"Configuration file {self.config_path} not found")
        
        # Check logs directory
        logs_dir = Path("logs")
        if not logs_dir.exists():
            logs_dir.mkdir(exist_ok=True)
            self.logger.info("Created logs directory")
        
        if issues:
            self.logger.error("Environment validation failed:")
            for issue in issues:
                self.logger.error(f"  - {issue}")
            return False
        
        self.logger.info("✅ Environment validation passed")
        return True
    
    async def validate_configuration(self) -> bool:
        """Validate system configuration"""
        self.logger.info("🔍 Validating configuration...")
        
        try:
            config_loader = get_config_loader()
            system_config = config_loader.load_system_config(
                environment=os.getenv('ENVIRONMENT', 'production')
            )
            
            # Validate configuration
            issues = config_loader.validate_configuration(system_config)
            if issues:
                self.logger.warning("Configuration issues found:")
                for issue in issues:
                    self.logger.warning(f"  - {issue}")
                return False
            
            # Print configuration summary
            config_summary = config_loader.get_config_summary(system_config)
            self.logger.info("Configuration Summary:")
            for key, value in config_summary.items():
                self.logger.info(f"  {key}: {value}")
            
            self.logger.info("✅ Configuration validation passed")
            return True
            
        except Exception as e:
            self.logger.error(f"Configuration validation failed: {e}")
            return False
    
    async def start_system(self, environment: str = "production", strategy: Optional[str] = None) -> bool:
        """Start the complete trading system"""
        self.logger.info("🚀 Starting trading system...")
        
        try:
            # Initialize orchestrator
            self.orchestrator = MasterOrchestrator(config_path=self.config_path)
            
            if not await self.orchestrator.initialize():
                self.logger.error("Failed to initialize orchestrator")
                return False
            
            # Start the system
            await self.orchestrator.start()
            self.running = True
            
            self.logger.info("✅ Trading system started successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to start trading system: {e}")
            return False
    
    async def stop_system(self):
        """Stop the trading system gracefully"""
        if not self.running:
            return
        
        self.logger.info("🛑 Stopping trading system...")
        
        try:
            if self.orchestrator:
                await self.orchestrator.stop()
                self.orchestrator = None
            
            self.running = False
            self.logger.info("✅ Trading system stopped")
            
        except Exception as e:
            self.logger.error(f"Error stopping trading system: {e}")
    
    async def health_monitor(self, interval: int = 30):
        """Monitor system health"""
        while self.running:
            try:
                # Get system status
                if self.orchestrator:
                    status = self.orchestrator.get_system_status()
                    
                    # Log health status
                    if status['system_health'] != 'healthy':
                        self.logger.warning(f"System health: {status['system_health']}")
                    
                    # Log performance metrics
                    metrics = status.get('performance_metrics', {})
                    if metrics:
                        self.logger.info(f"Performance: {metrics}")
                
                await asyncio.sleep(interval)
                
            except Exception as e:
                self.logger.error(f"Health monitoring error: {e}")
                await asyncio.sleep(60)
    
    async def run(self, environment: str = "production", strategy: Optional[str] = None):
        """Run the complete trading system"""
        try:
            # Validate environment
            if not await self.validate_environment():
                return False
            
            # Validate configuration
            if not await self.validate_configuration():
                return False
            
            # Start system
            if not await self.start_system(environment, strategy):
                return False
            
            # Setup signal handlers
            def signal_handler(signum, frame):
                self.logger.info(f"Received signal {signum}, initiating shutdown...")
                asyncio.create_task(self.stop_system())
            
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
            
            # Start health monitoring
            health_task = asyncio.create_task(self.health_monitor())
            
            # Keep running
            self.logger.info("✅ Trading system is running!")
            self.logger.info("Press Ctrl+C to stop gracefully...")
            
            try:
                while self.running:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                self.logger.info("Received keyboard interrupt, shutting down...")
            finally:
                health_task.cancel()
                await self.stop_system()
            
            return True
            
        except Exception as e:
            self.logger.error(f"Trading system failed: {e}")
            await self.stop_system()
            return False

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Start the complete trading system")
    parser.add_argument("--environment", "-e", default="production",
                       choices=["development", "staging", "production"],
                       help="Environment to run in")
    parser.add_argument("--strategy", "-s", default=None,
                       help="Specific strategy to run")
    parser.add_argument("--config", "-c", default="config/settings.yaml",
                       help="Configuration file path")
    parser.add_argument("--debug", "-d", action="store_true",
                       help="Enable debug mode")
    parser.add_argument("--validate-only", action="store_true",
                       help="Only validate environment and configuration")
    
    args = parser.parse_args()
    
    # Setup logging
    setup_logging(environment=args.environment, debug=args.debug)
    logger = logging.getLogger("main")
    
    # Create system manager
    manager = TradingSystemManager(config_path=args.config)
    
    if args.validate_only:
        # Only validate
        logger.info("Running validation only...")
        
        env_ok = await manager.validate_environment()
        config_ok = await manager.validate_configuration()
        
        if env_ok and config_ok:
            logger.info("✅ All validations passed")
            return 0
        else:
            logger.error("❌ Validation failed")
            return 1
    else:
        # Run complete system
        success = await manager.run(
            environment=args.environment,
            strategy=args.strategy
        )
        
        return 0 if success else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
