import asyncio
import psutil
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field

from app.monitoring.logger import AgentLogger
from app.monitoring.metrics import MetricsCollector
from app.monitoring.tracing import get_tracer, trace_operation
from app.models.events import HealthStatus, AgentEvent, EventType


class BaseAgent(BaseModel, ABC):
    """Base class for all agents with monitoring and health capabilities"""
    
    agent_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    agent_type: str
    is_running: bool = False
    start_time: Optional[datetime] = None
    error_count: int = 0
    last_error: Optional[str] = None
    active_tasks: int = 0
    
    # Monitoring components
    logger: Optional[AgentLogger] = None
    metrics: Optional[MetricsCollector] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self.logger = AgentLogger(self.agent_id, self.agent_type)
        self._setup_monitoring()
    
    def _setup_monitoring(self):
        """Setup monitoring components - override in subclasses if needed"""
        pass
    
    async def start(self):
        """Start the agent"""
        if self.is_running:
            self.logger.warning("Agent already running", agent_id=self.agent_id)
            return
        
        self.start_time = datetime.now()
        self.is_running = True
        
        self.logger.log_agent_start()
        
        # Start health monitoring
        asyncio.create_task(self._health_monitor_loop())
        
        # Start the agent's main work
        await self._start_work()
    
    async def stop(self):
        """Stop the agent"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.logger.log_agent_stop()
        
        await self._stop_work()
    
    @abstractmethod
    async def _start_work(self):
        """Start the agent's main work - implement in subclasses"""
        pass
    
    @abstractmethod
    async def _stop_work(self):
        """Stop the agent's main work - implement in subclasses"""
        pass
    
    async def _health_monitor_loop(self):
        """Background health monitoring loop"""
        while self.is_running:
            try:
                await self._update_health_metrics()
                await asyncio.sleep(30)  # Health check every 30 seconds
            except Exception as e:
                self.logger.log_exception(e, {"context": "health_monitor"})
                await asyncio.sleep(60)  # Longer sleep on error
    
    async def _update_health_metrics(self):
        """Update health metrics"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            cpu_percent = process.cpu_percent()
            
            if self.metrics:
                self.metrics.update_agent_health(
                    self.agent_id,
                    self.agent_type,
                    memory_info.rss,  # Resident Set Size in bytes
                    cpu_percent
                )
            
            self.logger.debug("health_check",
                            memory_mb=memory_info.rss / 1024 / 1024,
                            cpu_percent=cpu_percent,
                            active_tasks=self.active_tasks,
                            error_count=self.error_count)
                            
        except Exception as e:
            self.logger.log_exception(e, {"context": "health_metrics"})
    
    def get_health_status(self) -> HealthStatus:
        """Get current health status"""
        try:
            process = psutil.Process()
            memory_info = process.memory_info()
            cpu_percent = process.cpu_percent()
            
            # Determine status based on metrics
            status = "healthy"
            if self.error_count > 10:
                status = "unhealthy"
            elif self.error_count > 5 or cpu_percent > 80:
                status = "degraded"
            elif not self.is_running:
                status = "offline"
            
            uptime = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
            
            return HealthStatus(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                status=status,
                last_heartbeat=datetime.now(),
                uptime=uptime,
                memory_usage=memory_info.rss / 1024 / 1024,  # MB
                cpu_usage=cpu_percent,
                active_tasks=self.active_tasks,
                error_count=self.error_count,
                last_error=self.last_error
            )
        except Exception as e:
            self.logger.log_exception(e, {"context": "get_health_status"})
            return HealthStatus(
                agent_id=self.agent_id,
                agent_type=self.agent_type,
                status="unhealthy",
                last_heartbeat=datetime.now(),
                uptime=0,
                memory_usage=0,
                cpu_usage=0,
                active_tasks=self.active_tasks,
                error_count=self.error_count + 1,
                last_error=str(e)
            )
    
    async def handle_error(self, error: Exception, context: Optional[Dict[str, Any]] = None):
        """Handle an error with proper logging and metrics"""
        self.error_count += 1
        self.last_error = str(error)
        
        self.logger.log_exception(error, context)
        
        if self.metrics:
            self.metrics.record_agent_error(self.agent_id, type(error).__name__)
    
    async def execute_task(self, task_name: str, task_func, *args, **kwargs):
        """Execute a task with proper tracing and error handling"""
        task_id = str(uuid.uuid4())
        
        async with trace_operation(self.agent_id, task_name, 
                                 metadata={"task_id": task_id}) as span_id:
            try:
                self.active_tasks += 1
                self.logger.log_task_start(task_name, task_id)
                
                start_time = datetime.now()
                result = await task_func(*args, **kwargs)
                duration = (datetime.now() - start_time).total_seconds()
                
                self.logger.log_task_complete(task_name, task_id, duration)
                return result
                
            except Exception as e:
                self.logger.log_task_failed(task_name, task_id, str(e))
                await self.handle_error(e, {"task_name": task_name, "task_id": task_id})
                raise
            finally:
                self.active_tasks = max(0, self.active_tasks - 1)
    
    def emit_event(self, event_type: EventType, data: Dict[str, Any]):
        """Emit an agent event"""
        event = AgentEvent(
            event_type=event_type,
            agent_id=self.agent_id,
            agent_type=self.agent_type,
            data=data
        )
        
        self.logger.info("agent_event",
                        event_type=event_type.value,
                        data=data)
        
        # In a real implementation, this would publish to an event bus
        # For now, just log it
        return event 