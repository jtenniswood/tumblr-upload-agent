import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from contextvars import ContextVar
from pydantic import BaseModel, Field
from app.monitoring.logger import set_trace_context, get_trace_context


class TraceSpan(BaseModel):
    """Represents a single span in a distributed trace"""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    agent_id: str
    operation: str
    start_time: datetime
    end_time: Optional[datetime] = None
    duration_ms: Optional[float] = None
    status: str = "started"  # started, completed, failed
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    tags: Dict[str, str] = Field(default_factory=dict)


class DistributedTracer:
    """Distributed tracing system for tracking requests across agents"""
    
    def __init__(self):
        self.spans: Dict[str, TraceSpan] = {}
        self.active_traces: Dict[str, List[str]] = {}  # trace_id -> list of span_ids
    
    async def start_span(self, agent_id: str, operation: str, 
                        parent_span_id: Optional[str] = None,
                        metadata: Optional[Dict[str, Any]] = None,
                        tags: Optional[Dict[str, str]] = None) -> str:
        """Start a new span and return its ID"""
        
        span_id = str(uuid.uuid4())
        
        # Determine trace ID
        if parent_span_id and parent_span_id in self.spans:
            trace_id = self.spans[parent_span_id].trace_id
        else:
            # Check if we have a trace context
            existing_trace_id = get_trace_context()
            trace_id = existing_trace_id or str(uuid.uuid4())
        
        # Create the span
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            agent_id=agent_id,
            operation=operation,
            start_time=datetime.now(),
            metadata=metadata or {},
            tags=tags or {}
        )
        
        # Store the span
        self.spans[span_id] = span
        
        # Track active traces
        if trace_id not in self.active_traces:
            self.active_traces[trace_id] = []
        self.active_traces[trace_id].append(span_id)
        
        # Set trace context for logging
        set_trace_context(trace_id)
        
        return span_id
    
    async def end_span(self, span_id: str, status: str = "completed", 
                      error: Optional[str] = None,
                      metadata: Optional[Dict[str, Any]] = None):
        """End a span and calculate duration"""
        
        if span_id not in self.spans:
            return
        
        span = self.spans[span_id]
        span.end_time = datetime.now()
        span.duration_ms = (span.end_time - span.start_time).total_seconds() * 1000
        span.status = status
        span.error = error
        
        if metadata:
            span.metadata.update(metadata)
    
    async def add_span_metadata(self, span_id: str, metadata: Dict[str, Any]):
        """Add metadata to an existing span"""
        if span_id in self.spans:
            self.spans[span_id].metadata.update(metadata)
    
    async def add_span_tags(self, span_id: str, tags: Dict[str, str]):
        """Add tags to an existing span"""
        if span_id in self.spans:
            self.spans[span_id].tags.update(tags)
    
    def get_trace(self, trace_id: str) -> List[TraceSpan]:
        """Get all spans for a trace"""
        if trace_id not in self.active_traces:
            return []
        
        span_ids = self.active_traces[trace_id]
        return [self.spans[span_id] for span_id in span_ids if span_id in self.spans]
    
    def get_span(self, span_id: str) -> Optional[TraceSpan]:
        """Get a specific span"""
        return self.spans.get(span_id)
    
    def get_active_traces(self) -> List[str]:
        """Get list of active trace IDs"""
        return list(self.active_traces.keys())
    
    def cleanup_completed_traces(self, max_age_hours: int = 24):
        """Clean up old completed traces"""
        cutoff_time = datetime.now().timestamp() - (max_age_hours * 3600)
        
        traces_to_remove = []
        for trace_id, span_ids in self.active_traces.items():
            # Check if all spans in trace are completed and old
            all_completed = True
            all_old = True
            
            for span_id in span_ids:
                if span_id in self.spans:
                    span = self.spans[span_id]
                    if span.status == "started":
                        all_completed = False
                    if span.start_time.timestamp() > cutoff_time:
                        all_old = False
            
            if all_completed and all_old:
                traces_to_remove.append(trace_id)
        
        # Remove old traces
        for trace_id in traces_to_remove:
            span_ids = self.active_traces[trace_id]
            for span_id in span_ids:
                if span_id in self.spans:
                    del self.spans[span_id]
            del self.active_traces[trace_id]
    
    def get_trace_summary(self, trace_id: str) -> Optional[Dict[str, Any]]:
        """Get a summary of a trace"""
        spans = self.get_trace(trace_id)
        if not spans:
            return None
        
        # Calculate trace duration
        start_times = [span.start_time for span in spans]
        end_times = [span.end_time for span in spans if span.end_time]
        
        if not start_times:
            return None
        
        trace_start = min(start_times)
        trace_end = max(end_times) if end_times else None
        trace_duration = (trace_end - trace_start).total_seconds() * 1000 if trace_end else None
        
        # Count span statuses
        status_counts = {}
        for span in spans:
            status_counts[span.status] = status_counts.get(span.status, 0) + 1
        
        # Get involved agents
        agents = list(set(span.agent_id for span in spans))
        
        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "agents": agents,
            "start_time": trace_start,
            "end_time": trace_end,
            "duration_ms": trace_duration,
            "status_counts": status_counts,
            "has_errors": any(span.error for span in spans)
        }


class TracingContext:
    """Context manager for automatic span lifecycle management"""
    
    def __init__(self, tracer: DistributedTracer, agent_id: str, operation: str,
                 parent_span_id: Optional[str] = None,
                 metadata: Optional[Dict[str, Any]] = None,
                 tags: Optional[Dict[str, str]] = None):
        self.tracer = tracer
        self.agent_id = agent_id
        self.operation = operation
        self.parent_span_id = parent_span_id
        self.metadata = metadata
        self.tags = tags
        self.span_id: Optional[str] = None
    
    async def __aenter__(self):
        self.span_id = await self.tracer.start_span(
            self.agent_id, 
            self.operation,
            self.parent_span_id,
            self.metadata,
            self.tags
        )
        return self.span_id
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.span_id:
            if exc_type:
                await self.tracer.end_span(
                    self.span_id, 
                    "failed", 
                    str(exc_val) if exc_val else "Unknown error"
                )
            else:
                await self.tracer.end_span(self.span_id, "completed")


# Global tracer instance
_global_tracer: Optional[DistributedTracer] = None


def get_tracer() -> DistributedTracer:
    """Get the global tracer instance"""
    global _global_tracer
    if _global_tracer is None:
        _global_tracer = DistributedTracer()
    return _global_tracer


def set_tracer(tracer: DistributedTracer):
    """Set the global tracer instance"""
    global _global_tracer
    _global_tracer = tracer


def trace_operation(agent_id: str, operation: str,
                   parent_span_id: Optional[str] = None,
                   metadata: Optional[Dict[str, Any]] = None,
                   tags: Optional[Dict[str, str]] = None) -> TracingContext:
    """Create a tracing context for an operation"""
    tracer = get_tracer()
    return TracingContext(tracer, agent_id, operation, parent_span_id, metadata, tags) 