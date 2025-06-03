import structlog
import logging
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from contextvars import ContextVar

# Context variable to track request across agents
current_trace_id: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def human_readable_processor(logger, method_name, event_dict):
    """Custom processor for human-readable log formatting"""
    timestamp = event_dict.pop('timestamp', datetime.now().isoformat())
    level = event_dict.pop('level', 'info').upper()
    event = event_dict.pop('event', 'unknown_event')
    agent_id = event_dict.pop('agent_id', 'unknown')
    agent_type = event_dict.pop('agent_type', 'unknown')
    
    # Build the main message
    message_parts = [f"[{timestamp}]", f"{level:5}", f"{agent_type}({agent_id}):", event]
    
    # Add important fields to the message
    important_fields = ['file_path', 'category', 'post_id', 'error', 'success', 'duration']
    details = []
    
    for field in important_fields:
        if field in event_dict:
            value = event_dict.pop(field)
            if field == 'duration' and isinstance(value, (int, float)):
                details.append(f"{field}={value:.3f}s")
            elif field == 'file_path':
                # Show just the filename for readability
                from pathlib import Path
                details.append(f"file={Path(str(value)).name}")
            else:
                details.append(f"{field}={value}")
    
    # Add remaining fields as key=value pairs
    for key, value in event_dict.items():
        if key not in ['logger', 'exc_info'] and not key.startswith('_'):
            if isinstance(value, str) and len(value) > 50:
                value = value[:47] + "..."
            details.append(f"{key}={value}")
    
    if details:
        message_parts.append(f"({', '.join(details)})")
    
    return ' '.join(message_parts)


def configure_logging(log_level: str = "INFO", human_readable: bool = True):
    """Configure structured logging for the entire system"""
    
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, log_level.upper())
    )
    
    # Choose processors based on format preference
    if human_readable:
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            human_readable_processor,
        ]
    else:
        # JSON format (original)
        processors = [
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.JSONRenderer()
        ]
    
    # Configure structlog
    structlog.configure(
        processors=processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


class AgentLogger:
    """Structured logger for agents with automatic trace context"""
    
    def __init__(self, agent_id: str, agent_type: str):
        self.agent_id = agent_id
        self.agent_type = agent_type
        self.logger = structlog.get_logger().bind(
            agent_id=agent_id,
            agent_type=agent_type
        )
    
    def _add_trace_context(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Add trace ID to log context if available"""
        trace_id = current_trace_id.get()
        if trace_id:
            kwargs['trace_id'] = trace_id
        return kwargs
    
    def info(self, event: str, **kwargs):
        """Log info level event"""
        kwargs = self._add_trace_context(kwargs)
        self.logger.info(event, **kwargs)
    
    def warning(self, event: str, **kwargs):
        """Log warning level event"""
        kwargs = self._add_trace_context(kwargs)
        self.logger.warning(event, **kwargs)
    
    def error(self, event: str, **kwargs):
        """Log error level event"""
        kwargs = self._add_trace_context(kwargs)
        self.logger.error(event, **kwargs)
    
    def debug(self, event: str, **kwargs):
        """Log debug level event"""
        kwargs = self._add_trace_context(kwargs)
        self.logger.debug(event, **kwargs)
    
    def log_agent_start(self):
        """Log agent startup"""
        self.info("agent_started", timestamp=datetime.now().isoformat())
    
    def log_agent_stop(self):
        """Log agent shutdown"""
        self.info("agent_stopped", timestamp=datetime.now().isoformat())
    
    def log_task_start(self, task_type: str, task_id: str, **metadata):
        """Log task start"""
        self.info("task_started", 
                 task_type=task_type, 
                 task_id=task_id,
                 **metadata)
    
    def log_task_complete(self, task_type: str, task_id: str, duration: float, **metadata):
        """Log task completion"""
        self.info("task_completed", 
                 task_type=task_type, 
                 task_id=task_id, 
                 duration=duration,
                 **metadata)
    
    def log_task_failed(self, task_type: str, task_id: str, error: str, **metadata):
        """Log task failure"""
        self.error("task_failed", 
                  task_type=task_type, 
                  task_id=task_id, 
                  error=error,
                  **metadata)
    
    def log_exception(self, exception: Exception, context: Optional[Dict[str, Any]] = None):
        """Log exception with context"""
        self.error("exception_occurred",
                  error_type=type(exception).__name__,
                  error_message=str(exception),
                  context=context or {},
                  exc_info=True)
    
    def log_file_event(self, event_type: str, file_path: str, category: str, **metadata):
        """Log file-related events"""
        self.info("file_event",
                 event_type=event_type,
                 file_path=file_path,
                 category=category,
                 **metadata)
    
    def log_upload_event(self, event_type: str, file_path: str, category: str, 
                        success: Optional[bool] = None, error: Optional[str] = None, **metadata):
        """Log upload-related events"""
        log_data = {
            "event_type": event_type,
            "file_path": file_path,
            "category": category,
            **metadata
        }
        
        if success is not None:
            log_data["success"] = success
        if error:
            log_data["error"] = error
            
        if success is False or error:
            self.error("upload_event", **log_data)
        else:
            self.info("upload_event", **log_data)


def set_trace_context(trace_id: str):
    """Set the current trace ID for logging context"""
    current_trace_id.set(trace_id)


def get_trace_context() -> Optional[str]:
    """Get the current trace ID"""
    return current_trace_id.get()


def clear_trace_context():
    """Clear the current trace ID"""
    current_trace_id.set(None) 