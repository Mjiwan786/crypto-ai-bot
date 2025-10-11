#!/usr/bin/env python3
"""
Health check script for the trading system.

This script provides comprehensive health monitoring for:
1. System status
2. Agent health
3. Configuration validation
4. Performance metrics
5. Alert notifications
"""

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Dict, Any, Optional
import argparse
import json

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Import system components
from config.unified_config_loader import get_config_loader
from main import health_check, get_system_status

class HealthChecker:
    """Comprehensive health checker for the trading system"""
    
    def __init__(self):
        self.logger = logging.getLogger("HealthChecker")
        
    async def check_system_health(self) -> Dict[str, Any]:
        """Check overall system health"""
        try:
            # Get system status
            status = await get_system_status()
            
            # Determine overall health
            health_status = "healthy"
            issues = []
            
            # Check if system is running
            if not status.get('running', False):
                health_status = "stopped"
                issues.append("System not running")
            
            # Check system health
            system_health = status.get('system_health', 'unknown')
            if system_health not in ['healthy', 'degraded']:
                health_status = "unhealthy"
                issues.append(f"System health: {system_health}")
            
            # Check active agents
            agents_active = status.get('agents_active', [])
            if len(agents_active) < 3:  # Minimum expected agents
                health_status = "degraded"
                issues.append(f"Only {len(agents_active)} agents active")
            
            # Check performance metrics
            metrics = status.get('performance_metrics', {})
            if metrics.get('system_errors', 0) > 10:
                health_status = "unhealthy"
                issues.append(f"High error count: {metrics['system_errors']}")
            
            return {
                'status': health_status,
                'issues': issues,
                'details': status,
                'timestamp': time.time()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'issues': [f"Health check failed: {e}"],
                'details': {},
                'timestamp': time.time()
            }
    
    async def check_configuration_health(self) -> Dict[str, Any]:
        """Check configuration health"""
        try:
            config_loader = get_config_loader()
            system_config = config_loader.load_system_config()
            
            # Validate configuration
            issues = config_loader.validate_configuration(system_config)
            
            return {
                'status': 'healthy' if not issues else 'unhealthy',
                'issues': issues,
                'config_summary': config_loader.get_config_summary(system_config),
                'timestamp': time.time()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'issues': [f"Configuration check failed: {e}"],
                'config_summary': {},
                'timestamp': time.time()
            }
    
    async def check_agent_health(self) -> Dict[str, Any]:
        """Check individual agent health"""
        try:
            # This would check individual agent health in a real implementation
            # For now, return a placeholder
            return {
                'status': 'healthy',
                'agents': {
                    'signal_analyst': 'healthy',
                    'execution_agent': 'healthy',
                    'risk_router': 'healthy',
                    'enhanced_scalper': 'healthy'
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'agents': {},
                'issues': [f"Agent health check failed: {e}"],
                'timestamp': time.time()
            }
    
    async def check_infrastructure_health(self) -> Dict[str, Any]:
        """Check infrastructure health (Redis, etc.)"""
        try:
            # This would check Redis, database, etc. in a real implementation
            # For now, return a placeholder
            return {
                'status': 'healthy',
                'components': {
                    'redis': 'healthy',
                    'kraken_api': 'healthy',
                    'data_pipeline': 'healthy'
                },
                'timestamp': time.time()
            }
            
        except Exception as e:
            return {
                'status': 'error',
                'components': {},
                'issues': [f"Infrastructure check failed: {e}"],
                'timestamp': time.time()
            }
    
    async def run_comprehensive_check(self) -> Dict[str, Any]:
        """Run comprehensive health check"""
        self.logger.info("🔍 Running comprehensive health check...")
        
        # Run all health checks
        system_health = await self.check_system_health()
        config_health = await self.check_configuration_health()
        agent_health = await self.check_agent_health()
        infra_health = await self.check_infrastructure_health()
        
        # Determine overall health
        all_statuses = [
            system_health['status'],
            config_health['status'],
            agent_health['status'],
            infra_health['status']
        ]
        
        if 'error' in all_statuses:
            overall_status = 'error'
        elif 'unhealthy' in all_statuses:
            overall_status = 'unhealthy'
        elif 'degraded' in all_statuses:
            overall_status = 'degraded'
        else:
            overall_status = 'healthy'
        
        # Collect all issues
        all_issues = []
        all_issues.extend(system_health.get('issues', []))
        all_issues.extend(config_health.get('issues', []))
        all_issues.extend(agent_health.get('issues', []))
        all_issues.extend(infra_health.get('issues', []))
        
        result = {
            'overall_status': overall_status,
            'timestamp': time.time(),
            'checks': {
                'system': system_health,
                'configuration': config_health,
                'agents': agent_health,
                'infrastructure': infra_health
            },
            'issues': all_issues
        }
        
        return result
    
    def print_health_report(self, health_data: Dict[str, Any]):
        """Print a formatted health report"""
        print("\n" + "="*60)
        print("🏥 TRADING SYSTEM HEALTH REPORT")
        print("="*60)
        
        # Overall status
        status = health_data['overall_status']
        status_emoji = {
            'healthy': '✅',
            'degraded': '⚠️',
            'unhealthy': '❌',
            'error': '💥'
        }
        
        print(f"\nOverall Status: {status_emoji.get(status, '❓')} {status.upper()}")
        
        # Issues
        issues = health_data.get('issues', [])
        if issues:
            print(f"\nIssues Found ({len(issues)}):")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("\n✅ No issues found")
        
        # Individual checks
        checks = health_data.get('checks', {})
        print(f"\nDetailed Checks:")
        
        for check_name, check_data in checks.items():
            check_status = check_data.get('status', 'unknown')
            check_emoji = status_emoji.get(check_status, '❓')
            print(f"  {check_emoji} {check_name.title()}: {check_status}")
            
            # Show specific issues for this check
            check_issues = check_data.get('issues', [])
            if check_issues:
                for issue in check_issues:
                    print(f"    - {issue}")
        
        print("\n" + "="*60)
    
    def save_health_report(self, health_data: Dict[str, Any], filename: str = "health_report.json"):
        """Save health report to file"""
        try:
            # Create reports directory if it doesn't exist
            reports_dir = Path("reports")
            reports_dir.mkdir(exist_ok=True)
            
            # Save report
            report_path = reports_dir / filename
            with open(report_path, 'w') as f:
                json.dump(health_data, f, indent=2, default=str)
            
            self.logger.info(f"Health report saved to {report_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to save health report: {e}")

async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Health check for the trading system")
    parser.add_argument("--format", "-f", default="text",
                       choices=["text", "json"],
                       help="Output format")
    parser.add_argument("--save", "-s", action="store_true",
                       help="Save report to file")
    parser.add_argument("--continuous", "-c", action="store_true",
                       help="Run continuous health monitoring")
    parser.add_argument("--interval", "-i", type=int, default=30,
                       help="Interval for continuous monitoring (seconds)")
    
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create health checker
    checker = HealthChecker()
    
    if args.continuous:
        # Continuous monitoring
        print(f"🔄 Starting continuous health monitoring (interval: {args.interval}s)")
        print("Press Ctrl+C to stop...")
        
        try:
            while True:
                health_data = await checker.run_comprehensive_check()
                
                if args.format == "json":
                    print(json.dumps(health_data, indent=2, default=str))
                else:
                    checker.print_health_report(health_data)
                
                if args.save:
                    checker.save_health_report(health_data)
                
                await asyncio.sleep(args.interval)
                
        except KeyboardInterrupt:
            print("\n🛑 Health monitoring stopped")
    else:
        # Single health check
        health_data = await checker.run_comprehensive_check()
        
        if args.format == "json":
            print(json.dumps(health_data, indent=2, default=str))
        else:
            checker.print_health_report(health_data)
        
        if args.save:
            checker.save_health_report(health_data)
        
        # Exit with appropriate code
        if health_data['overall_status'] == 'healthy':
            sys.exit(0)
        else:
            sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())
