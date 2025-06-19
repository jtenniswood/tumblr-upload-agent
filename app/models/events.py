from pydantic import BaseModel, Field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Dict, List
from enum import Enum


class EventType(str, Enum):
    FILE_DETECTED = "file_detected"
    UPLOAD_REQUESTED = "upload_requested"
    ANALYSIS_COMPLETED = "analysis_completed"
    UPLOAD_COMPLETED = "upload_completed"
    UPLOAD_FAILED = "upload_failed"
    AGENT_STARTED = "agent_started"
    AGENT_STOPPED = "agent_stopped"
    HEALTH_CHECK = "health_check"
    ERROR_OCCURRED = "error_occurred"


class FileEvent(BaseModel):
    """Event triggered when a file is detected"""
    event_type: EventType = EventType.FILE_DETECTED
    file_path: Path
    category: str
    file_size: int
    timestamp: datetime = Field(default_factory=datetime.now)
    trace_id: Optional[str] = None


class UploadRequest(BaseModel):
    """Request to upload a file to Tumblr"""
    file_path: Path
    category: str
    tags: List[str]
    caption: Optional[str] = None
    state: str = "published"
    trace_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ImageAnalysis(BaseModel):
    """Result of image analysis"""
    file_path: Path
    description: Optional[str] = None
    confidence: Optional[float] = None
    error: Optional[str] = None
    analysis_time: float = 0.0
    trace_id: Optional[str] = None


class UploadResult(BaseModel):
    """Result of upload attempt"""
    success: bool
    post_id: Optional[str] = None
    error_message: Optional[str] = None
    error_type: Optional[str] = None
    upload_time: float = 0.0
    file_path: Path
    category: str
    trace_id: Optional[str] = None


class AgentEvent(BaseModel):
    """Generic agent event"""
    event_type: EventType
    agent_id: str
    agent_type: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    trace_id: Optional[str] = None


class HealthStatus(BaseModel):
    """Agent health status"""
    agent_id: str
    agent_type: str
    status: str  # healthy, degraded, unhealthy, offline
    last_heartbeat: datetime
    uptime: float
    memory_usage: float
    cpu_usage: float
    active_tasks: int
    error_count: int
    last_error: Optional[str] = None


class TaskEvent(BaseModel):
    """Task lifecycle event"""
    task_id: str
    task_type: str
    agent_id: str
    status: str  # started, completed, failed
    duration: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)
    trace_id: Optional[str] = None 