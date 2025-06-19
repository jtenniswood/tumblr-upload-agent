#!/usr/bin/env python3
"""
Tumblr Upload Agent System
A multi-agent system for automatically uploading images to Tumblr with AI-powered descriptions.
"""

import asyncio
import signal
import sys
import os
from pathlib import Path

from .models.config import SystemConfig
from .agents.orchestrator import UploadOrchestratorAgent
from .monitoring.logger import configure_logging


class TumblrUploadSystem:
    """Main system controller"""
    
    def __init__(self):
        self.orchestrator: UploadOrchestratorAgent = None
        self.running = False
    
    async def start(self):
        """Start the system"""
        try:
            # Load configuration
            config = SystemConfig()
            
            # Configure logging
            configure_logging(config.monitoring.log_level, config.monitoring.human_readable_logs)
            
            # Create orchestrator
            self.orchestrator = UploadOrchestratorAgent(
                config=config,
                agent_id="main_orchestrator"
            )
            
            # Validate system before starting
            print("🔍 Validating system configuration...")
            validation_results = await self.orchestrator.validate_system()
            
            # Check critical validations (image_analysis is optional)
            critical_validations = ['tumblr_connection', 'directories_accessible', 'metrics_working']
            failed_critical = [k for k in critical_validations if not validation_results.get(k, False)]
            
            if failed_critical:
                print(f"❌ Critical system validation failed: {failed_critical}")
                print("Please check your configuration and try again.")
                return False
            
            # Report optional validations
            optional_validations = ['image_analysis']
            failed_optional = [k for k in optional_validations if not validation_results.get(k, False)]
            
            if failed_optional:
                print(f"⚠️  Optional features disabled: {failed_optional}")
                print("   (System will continue without these features)")
            
            print("✅ System validation passed")
            
            # Start the orchestrator
            print("🚀 Starting Tumblr Upload Agent System...")
            await self.orchestrator.start()
            
            self.running = True
            print("✅ System started successfully!")
            
            # Print system status
            await self._print_status()
            
            return True
            
        except Exception as e:
            print(f"❌ Failed to start system: {e}")
            return False
    
    async def stop(self):
        """Stop the system"""
        if self.orchestrator and self.running:
            print("\n🛑 Stopping Tumblr Upload Agent System...")
            await self.orchestrator.stop()
            self.running = False
            print("✅ System stopped successfully")
    
    async def _print_status(self):
        """Print current system status"""
        try:
            status = await self.orchestrator.get_system_status()
            
            print("\n📊 System Status:")
            print(f"   Orchestrator: {status.get('orchestrator', {}).get('status', 'unknown')}")
            
            agents = status.get('agents', {})
            for agent_name, agent_status in agents.items():
                print(f"   {agent_name}: {agent_status.get('status', 'unknown')}")
            
            rate_limits = status.get('rate_limits', {})
            if rate_limits:
                print(f"\n⏱️  Rate Limits:")
                print(f"   Hourly: {rate_limits.get('hourly_uploads', 0)}/{rate_limits.get('hourly_limit', 0)}")
                print(f"   Daily: {rate_limits.get('daily_uploads', 0)}/{rate_limits.get('daily_limit', 0)}")
                print(f"   Can upload now: {rate_limits.get('can_upload_now', False)}")
            
            queue_size = status.get('queue_size', 0)
            print(f"\n📁 Queue: {queue_size} files pending")
            
            metrics = status.get('metrics', {})
            if metrics:
                print(f"\n📈 Metrics:")
                print(f"   Uptime: {metrics.get('uptime_seconds', 0):.0f} seconds")
                print(f"   Success rate: {metrics.get('success_rate', 0):.2%}")
            
        except Exception as e:
            print(f"❌ Failed to get status: {e}")
    
    async def run_forever(self):
        """Run the system until interrupted"""
        try:
            while self.running:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            await self.stop()


async def main():
    """Main entry point"""
    system = TumblrUploadSystem()
    
    # Setup signal handlers
    def signal_handler(signum, frame):
        print(f"\n🔔 Received signal {signum}")
        asyncio.create_task(system.stop())
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Start system
    if await system.start():
        try:
            await system.run_forever()
        except Exception as e:
            print(f"❌ System error: {e}")
            await system.stop()
    
    print("👋 Goodbye!")


if __name__ == "__main__":
    # Check Python version
    if sys.version_info < (3, 8):
        print("❌ Python 3.8 or higher is required")
        sys.exit(1)
    
    # Run the system
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Goodbye!")
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1) 