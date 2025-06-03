import asyncio
import os
import threading
from pathlib import Path
from typing import Dict, List, AsyncGenerator, Optional, Any
from watchdog.observers.polling import PollingObserver
from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from pydantic import Field

from app.agents.base import BaseAgent
from app.models.config import FileWatcherConfig
from app.models.events import FileEvent, EventType
from app.monitoring.tracing import trace_operation


class FileEventHandler(FileSystemEventHandler):
    """Watchdog event handler that queues file events"""
    
    def __init__(self, agent: 'FileWatcherAgent', category: str):
        super().__init__()
        self.agent = agent
        self.category = category
    
    def on_created(self, event):
        """Handle file creation events"""
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Check if file extension is allowed
        if file_path.suffix.lower() not in self.agent.config.file_extensions:
            return
        
        # Create file event
        file_event = FileEvent(
            file_path=file_path,
            category=self.category,
            file_size=file_path.stat().st_size if file_path.exists() else 0
        )
        
        # Queue the event using thread-safe approach
        if self.agent.event_loop and self.agent.file_event_queue:
            try:
                # Use call_soon_threadsafe to schedule the coroutine
                future = asyncio.run_coroutine_threadsafe(
                    self.agent._queue_file_event(file_event),
                    self.agent.event_loop
                )
                # Don't wait for the result to avoid blocking the watchdog thread
            except Exception as e:
                # Log error but don't crash the watchdog thread
                print(f"Error queuing file event: {e}")


class FileWatcherAgent(BaseAgent):
    """Agent responsible for monitoring directories and detecting new files"""
    
    agent_type: str = "file_watcher"
    config: FileWatcherConfig = Field(...)
    observers: List[PollingObserver] = Field(default_factory=list)
    file_event_queue: Optional[asyncio.Queue] = None
    event_loop: Optional[asyncio.AbstractEventLoop] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self.file_event_queue = asyncio.Queue()
        self.observers = []
        self.event_loop = None
    
    async def _start_work(self):
        """Start watching directories"""
        # Store the current event loop for thread-safe communication
        self.event_loop = asyncio.get_running_loop()
        
        await self._setup_directories()
        await self._start_observers()
        
        # Note: We don't start _process_events() here anymore since the orchestrator
        # will consume events directly via get_file_events()
        self.logger.info("file_watcher_started", note="orchestrator_will_consume_events")
    
    async def _stop_work(self):
        """Stop watching directories"""
        await self._stop_observers()
    
    async def _setup_directories(self):
        """Create directories if they don't exist"""
        try:
            # Get current categories (auto-discovered or configured)
            categories = self.config.get_categories()
            
            # Create base upload directory
            self.config.base_upload_folder.mkdir(parents=True, exist_ok=True)
            
            # Create category subdirectories
            for category in categories:
                category_path = self.config.base_upload_folder / category
                category_path.mkdir(parents=True, exist_ok=True)
                
                self.logger.info("directory_created",
                               category=category,
                               path=str(category_path))
                               
        except Exception as e:
            await self.handle_error(e, {"context": "setup_directories"})
            raise
    
    async def _start_observers(self):
        """Start file system observers for each category"""
        try:
            # Get current categories (auto-discovered or configured)
            categories = self.config.get_categories()
            
            for category in categories:
                category_path = self.config.base_upload_folder / category
                
                if not category_path.exists():
                    self.logger.warning("category_path_missing",
                                      category=category,
                                      path=str(category_path))
                    continue
                
                # Create event handler
                event_handler = FileEventHandler(self, category)
                
                # Create observer
                observer = PollingObserver()
                observer.schedule(event_handler, str(category_path), recursive=False)
                observer.start()
                
                self.observers.append(observer)
                
                self.logger.info("observer_started",
                               category=category,
                               path=str(category_path))
                               
        except Exception as e:
            await self.handle_error(e, {"context": "start_observers"})
            raise
    
    async def _stop_observers(self):
        """Stop all file system observers"""
        for observer in self.observers:
            try:
                observer.stop()
                observer.join(timeout=5.0)
            except Exception as e:
                self.logger.error("observer_stop_error", error=str(e))
        
        self.observers.clear()
        self.logger.info("observers_stopped")
    
    async def _queue_file_event(self, file_event: FileEvent):
        """Queue a file event for processing"""
        try:
            if self.file_event_queue:
                await self.file_event_queue.put(file_event)
            
            self.logger.log_file_event("file_detected",
                                     str(file_event.file_path),
                                     file_event.category,
                                     file_size=file_event.file_size)
            
            if self.metrics:
                self.metrics.record_file_detected(file_event.category)
                
        except Exception as e:
            await self.handle_error(e, {"context": "queue_file_event"})
    
    async def get_file_events(self) -> AsyncGenerator[FileEvent, None]:
        """Get file events as they are detected"""
        while self.is_running:
            try:
                if not self.file_event_queue:
                    await asyncio.sleep(1.0)
                    continue
                    
                file_event = await asyncio.wait_for(
                    self.file_event_queue.get(),
                    timeout=1.0
                )
                yield file_event
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                await self.handle_error(e, {"context": "get_file_events"})
                await asyncio.sleep(1.0)
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        if self.file_event_queue:
            return self.file_event_queue.qsize()
        return 0
    
    async def scan_existing_files(self):
        """Scan for existing files in watched directories"""
        self.logger.info("scanning_existing_files")
        
        # Get current categories (auto-discovered or configured)
        categories = self.config.get_categories()
        
        for category in categories:
            category_path = self.config.base_upload_folder / category
            
            if not category_path.exists():
                continue
            
            try:
                for file_path in category_path.iterdir():
                    if file_path.is_file() and file_path.suffix.lower() in self.config.file_extensions:
                        file_event = FileEvent(
                            file_path=file_path,
                            category=category,
                            file_size=file_path.stat().st_size
                        )
                        await self._queue_file_event(file_event)
                        
            except Exception as e:
                await self.handle_error(e, {"context": "scan_existing_files", "category": category}) 