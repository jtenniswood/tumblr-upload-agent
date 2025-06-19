"""
Metrics collection and monitoring for the Tumblr Upload Agent System
"""

import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import defaultdict, deque
from threading import Lock

from .logger import AgentLogger


class MetricsCollector:
    """Collects and manages system metrics"""
    
    def __init__(self, agent_id: str = "system"):
        self.agent_id = agent_id
        self.logger = AgentLogger(agent_id, "metrics")
        self.start_time = time.time()
        
        # Thread-safe metrics storage
        self._lock = Lock()
        
        # Agent health metrics
        self.agent_health: Dict[str, Dict[str, Any]] = {}
        
        # Upload metrics
        self.upload_attempts = defaultdict(int)
        self.upload_successes = defaultdict(int)
        self.upload_failures = defaultdict(lambda: defaultdict(int))
        self.upload_times = deque(maxlen=100)  # Keep last 100 upload times
        
        # File detection metrics
        self.files_detected = defaultdict(int)
        
        # Image analysis metrics
        self.analysis_times = deque(maxlen=100)  # Keep last 100 analysis times
        
        # Image conversion metrics
        self.conversion_times = deque(maxlen=100)  # Keep last 100 conversion times
        self.conversions_performed = defaultdict(int)  # Track conversions by format
        
        # Error tracking
        self.agent_errors = defaultdict(lambda: defaultdict(int))
        
        # Rate limiting metrics
        self.hourly_uploads = deque(maxlen=1000)  # Track timestamps
        self.daily_uploads = deque(maxlen=10000)  # Track timestamps
    
    def update_agent_health(self, agent_id: str, agent_type: str, 
                          memory_usage: float, cpu_usage: float):
        """Update health metrics for an agent"""
        with self._lock:
            self.agent_health[agent_id] = {
                'agent_type': agent_type,
                'memory_usage': memory_usage,
                'cpu_usage': cpu_usage,
                'last_update': datetime.now(),
                'uptime': time.time() - self.start_time
            }
    
    def record_agent_error(self, agent_id: str, error_type: str):
        """Record an error for an agent"""
        with self._lock:
            self.agent_errors[agent_id][error_type] += 1
            
        self.logger.debug("agent_error_recorded", 
                         agent_id=agent_id, 
                         error_type=error_type)
    
    def record_file_detected(self, category: str):
        """Record a file detection event"""
        with self._lock:
            self.files_detected[category] += 1
            
        self.logger.debug("file_detected", category=category)
    
    def record_image_analysis(self, analysis_time: float):
        """Record image analysis timing"""
        with self._lock:
            self.analysis_times.append(analysis_time)
            
        self.logger.debug("image_analysis_completed", 
                         analysis_time=analysis_time)
    
    def record_image_conversion(self, conversion_time: float, from_format: str = "unknown"):
        """Record image conversion timing and format"""
        with self._lock:
            self.conversion_times.append(conversion_time)
            self.conversions_performed[from_format] += 1
            
        self.logger.debug("image_conversion_completed", 
                         conversion_time=conversion_time,
                         from_format=from_format)
    
    def record_upload_attempt(self, category: str):
        """Record an upload attempt"""
        with self._lock:
            self.upload_attempts[category] += 1
            
        self.logger.debug("upload_attempt", category=category)
    
    def record_upload_success(self, category: str, upload_time: float):
        """Record a successful upload"""
        timestamp = datetime.now()
        
        with self._lock:
            self.upload_successes[category] += 1
            self.upload_times.append(upload_time)
            
            # Track for rate limiting
            self.hourly_uploads.append(timestamp)
            self.daily_uploads.append(timestamp)
            
            # Clean old timestamps
            self._clean_old_timestamps()
            
        self.logger.info("upload_success", 
                        category=category, 
                        upload_time=upload_time)
    
    def record_upload_failure(self, category: str, error_type: str):
        """Record a failed upload"""
        with self._lock:
            self.upload_failures[category][error_type] += 1
            
        self.logger.warning("upload_failure", 
                           category=category, 
                           error_type=error_type)
    
    def _clean_old_timestamps(self):
        """Clean old timestamps for rate limiting (called with lock held)"""
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)
        
        # Clean hourly uploads
        while self.hourly_uploads and self.hourly_uploads[0] < hour_ago:
            self.hourly_uploads.popleft()
            
        # Clean daily uploads
        while self.daily_uploads and self.daily_uploads[0] < day_ago:
            self.daily_uploads.popleft()
    
    def get_upload_rate_limits(self, hourly_limit: int = 75, daily_limit: int = 250) -> Dict[str, Any]:
        """Get current rate limit status"""
        with self._lock:
            self._clean_old_timestamps()
            
            hourly_count = len(self.hourly_uploads)
            daily_count = len(self.daily_uploads)
            
            return {
                'hourly_uploads': hourly_count,
                'hourly_limit': hourly_limit,
                'hourly_remaining': max(0, hourly_limit - hourly_count),
                'daily_uploads': daily_count,
                'daily_limit': daily_limit,
                'daily_remaining': max(0, daily_limit - daily_count),
                'can_upload_now': hourly_count < hourly_limit and daily_count < daily_limit
            }
    
    def get_success_rate(self, category: Optional[str] = None) -> float:
        """Get upload success rate"""
        with self._lock:
            if category:
                attempts = self.upload_attempts[category]
                successes = self.upload_successes[category]
            else:
                attempts = sum(self.upload_attempts.values())
                successes = sum(self.upload_successes.values())
            
            if attempts == 0:
                return 0.0
            
            return successes / attempts
    
    def get_average_upload_time(self) -> float:
        """Get average upload time"""
        with self._lock:
            if not self.upload_times:
                return 0.0
            
            return sum(self.upload_times) / len(self.upload_times)
    
    def get_average_analysis_time(self) -> float:
        """Get average image analysis time"""
        with self._lock:
            if not self.analysis_times:
                return 0.0
            
            return sum(self.analysis_times) / len(self.analysis_times)
    
    def get_average_conversion_time(self) -> float:
        """Get average image conversion time"""
        with self._lock:
            if not self.conversion_times:
                return 0.0
            
            return sum(self.conversion_times) / len(self.conversion_times)
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get comprehensive system metrics"""
        with self._lock:
            uptime = time.time() - self.start_time
            
            return {
                'uptime_seconds': uptime,
                'agent_health': dict(self.agent_health),
                'upload_attempts': dict(self.upload_attempts),
                'upload_successes': dict(self.upload_successes),
                'upload_failures': {k: dict(v) for k, v in self.upload_failures.items()},
                'files_detected': dict(self.files_detected),
                'agent_errors': {k: dict(v) for k, v in self.agent_errors.items()},
                'success_rate': self.get_success_rate(),
                'average_upload_time': self.get_average_upload_time(),
                'average_analysis_time': self.get_average_analysis_time(),
                'average_conversion_time': self.get_average_conversion_time(),
                'conversions_performed': dict(self.conversions_performed),
                'rate_limits': self.get_upload_rate_limits()
            }
    
    def reset_metrics(self):
        """Reset all metrics (useful for testing)"""
        with self._lock:
            self.agent_health.clear()
            self.upload_attempts.clear()
            self.upload_successes.clear()
            self.upload_failures.clear()
            self.upload_times.clear()
            self.files_detected.clear()
            self.analysis_times.clear()
            self.conversion_times.clear()
            self.conversions_performed.clear()
            self.agent_errors.clear()
            self.hourly_uploads.clear()
            self.daily_uploads.clear()
            self.start_time = time.time()
            
        self.logger.info("metrics_reset")


# Global metrics collector instance
_global_metrics: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get the global metrics collector instance"""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics


def initialize_metrics(agent_id: str = "system") -> MetricsCollector:
    """Initialize the global metrics collector"""
    global _global_metrics
    _global_metrics = MetricsCollector(agent_id)
    return _global_metrics 