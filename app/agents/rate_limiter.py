import asyncio
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import deque
from pydantic import Field

from app.agents.base import BaseAgent
from app.models.config import RateLimitConfig
from app.monitoring.tracing import trace_operation


class RateLimitingAgent(BaseAgent):
    """Agent responsible for managing upload timing and API rate limits"""
    
    agent_type: str = "rate_limiter"
    config: RateLimitConfig = Field(...)
    upload_history: deque = Field(default_factory=deque)
    daily_uploads: int = 0
    last_reset_date: Optional[datetime] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    # Rate limiting state
    last_upload_time: float = 0
    upload_times: deque = None  # Track recent upload times
    hourly_uploads: int = 0
    current_hour: int = 0
    
    def __init__(self, **data):
        super().__init__(**data)
        self.upload_history = deque()
        self.daily_uploads = 0
        self.last_reset_date = datetime.now().date()
        self.upload_times = deque(maxlen=self.config.burst_limit)
        self.current_hour = datetime.now().hour
    
    async def _start_work(self):
        """Start the rate limiting agent"""
        # Start periodic reset task
        asyncio.create_task(self._periodic_reset())
        
        self.logger.info("rate_limiter_started",
                        upload_delay=self.config.upload_delay,
                        max_per_hour=self.config.max_uploads_per_hour,
                        max_per_day=self.config.max_uploads_per_day,
                        burst_limit=self.config.burst_limit)
    
    async def _stop_work(self):
        """Stop the rate limiting agent"""
        self.logger.info("rate_limiter_stopped")
    
    async def should_allow_upload(self) -> bool:
        """Check if an upload should be allowed based on rate limits"""
        return await self.execute_task("should_allow_upload", self._should_allow_upload_impl)
    
    async def _should_allow_upload_impl(self) -> bool:
        """Implementation of rate limit checking"""
        async with trace_operation(self.agent_id, "check_rate_limit") as span_id:
            
            current_time = time.time()
            now = datetime.now()
            
            # Check if we need to reset hourly/daily counters
            if now.hour != self.current_hour:
                self.hourly_uploads = 0
                self.current_hour = now.hour
                self.logger.info("hourly_counter_reset", hour=now.hour)
            
            # Check daily limit
            if self.daily_uploads >= self.config.max_uploads_per_day:
                self.logger.warning("daily_limit_reached",
                                  uploads=self.daily_uploads,
                                  limit=self.config.max_uploads_per_day)
                
                return False
            
            # Check hourly limit
            if self.hourly_uploads >= self.config.max_uploads_per_hour:
                self.logger.warning("hourly_limit_reached",
                                  uploads=self.hourly_uploads,
                                  limit=self.config.max_uploads_per_hour)
                
                return False
            
            # Check minimum delay between uploads
            time_since_last = current_time - self.last_upload_time
            if time_since_last < self.config.upload_delay:
                remaining_delay = self.config.upload_delay - time_since_last
                self.logger.debug("upload_delay_active",
                                time_since_last=time_since_last,
                                remaining_delay=remaining_delay)
                
                return False
            
            # Check burst limit (uploads in quick succession)
            if len(self.upload_times) >= self.config.burst_limit:
                oldest_upload = self.upload_times[0]
                if current_time - oldest_upload < 60:  # Within last minute
                    self.logger.warning("burst_limit_reached",
                                      uploads_in_minute=len(self.upload_times),
                                      limit=self.config.burst_limit)
                    
                    return False
            
            self.logger.debug("upload_allowed",
                            hourly_uploads=self.hourly_uploads,
                            daily_uploads=self.daily_uploads,
                            time_since_last=time_since_last)
            
            return True
    
    async def record_upload(self):
        """Record that an upload has occurred"""
        return await self.execute_task("record_upload", self._record_upload_impl)
    
    async def _record_upload_impl(self):
        """Implementation of upload recording"""
        async with trace_operation(self.agent_id, "record_upload") as span_id:
            
            current_time = time.time()
            
            # Update counters
            self.last_upload_time = current_time
            self.hourly_uploads += 1
            self.daily_uploads += 1
            
            # Track for burst limiting
            self.upload_times.append(current_time)
            
            self.logger.info("upload_recorded",
                           hourly_uploads=self.hourly_uploads,
                           daily_uploads=self.daily_uploads,
                           uploads_in_burst_window=len(self.upload_times))
    
    async def wait_for_next_slot(self) -> float:
        """Wait until the next upload slot is available"""
        return await self.execute_task("wait_for_next_slot", self._wait_for_next_slot_impl)
    
    async def _wait_for_next_slot_impl(self) -> float:
        """Implementation of waiting for next upload slot"""
        async with trace_operation(self.agent_id, "wait_for_slot") as span_id:
            
            wait_time = await self._calculate_wait_time()
            
            if wait_time > 0:
                self.logger.info("waiting_for_rate_limit",
                               wait_time=wait_time)
                
                await asyncio.sleep(wait_time)
            
            return wait_time
    
    async def _calculate_wait_time(self) -> float:
        """Calculate how long to wait before next upload is allowed"""
        current_time = time.time()
        now = datetime.now()
        
        wait_times = []
        
        # Check minimum delay
        time_since_last = current_time - self.last_upload_time
        if time_since_last < self.config.upload_delay:
            wait_times.append(self.config.upload_delay - time_since_last)
        
        # Check burst limit
        if len(self.upload_times) >= self.config.burst_limit:
            oldest_upload = self.upload_times[0]
            time_until_burst_reset = 60 - (current_time - oldest_upload)
            if time_until_burst_reset > 0:
                wait_times.append(time_until_burst_reset)
        
        # Check hourly limit
        if self.hourly_uploads >= self.config.max_uploads_per_hour:
            # Wait until next hour
            next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            wait_times.append((next_hour - now).total_seconds())
        
        # Check daily limit
        if self.daily_uploads >= self.config.max_uploads_per_day:
            # Wait until next day
            next_day = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            wait_times.append((next_day - now).total_seconds())
        
        return max(wait_times) if wait_times else 0
    
    async def _periodic_reset(self):
        """Periodic task to reset counters and clean up old data"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Check every 5 minutes
                await self._cleanup_old_data()
            except Exception as e:
                self.logger.error("periodic_reset_error", error=str(e))
                await asyncio.sleep(300)
    
    async def _cleanup_old_data(self):
        """Clean up old upload time data"""
        current_time = time.time()
        
        # Remove upload times older than 1 minute for burst limiting
        while self.upload_times and current_time - self.upload_times[0] > 60:
            self.upload_times.popleft()
    
    def get_rate_limit_status(self) -> Dict:
        """Get current rate limiting status"""
        current_time = time.time()
        now = datetime.now()
        
        # Calculate remaining limits
        hourly_remaining = max(0, self.config.max_uploads_per_hour - self.hourly_uploads)
        daily_remaining = max(0, self.config.max_uploads_per_day - self.daily_uploads)
        
        # Calculate time until next allowed upload
        time_since_last = current_time - self.last_upload_time
        delay_remaining = max(0, self.config.upload_delay - time_since_last)
        
        # Calculate burst window status
        burst_remaining = max(0, self.config.burst_limit - len(self.upload_times))
        
        return {
            "hourly_uploads": self.hourly_uploads,
            "hourly_limit": self.config.max_uploads_per_hour,
            "hourly_remaining": hourly_remaining,
            "daily_uploads": self.daily_uploads,
            "daily_limit": self.config.max_uploads_per_day,
            "daily_remaining": daily_remaining,
            "delay_remaining": delay_remaining,
            "burst_remaining": burst_remaining,
            "uploads_in_burst_window": len(self.upload_times),
            "can_upload_now": delay_remaining == 0 and burst_remaining > 0 and hourly_remaining > 0 and daily_remaining > 0
        }
    
    async def reset_counters(self):
        """Reset all rate limiting counters (for testing/admin purposes)"""
        self.hourly_uploads = 0
        self.daily_uploads = 0
        self.upload_times.clear()
        self.last_upload_time = 0
        
        self.logger.info("rate_limit_counters_reset")
    
    async def get_estimated_wait_time(self) -> float:
        """Get estimated wait time for next upload"""
        return await self._calculate_wait_time() 