import asyncio
from pathlib import Path
from typing import Optional, Dict, Any
from datetime import datetime
from pydantic import Field

from app.agents.base import BaseAgent
from app.agents.file_watcher import FileWatcherAgent
from app.agents.image_analysis import ImageAnalysisAgent
from app.agents.tumblr_publisher import TumblrPublishingAgent
from app.agents.file_manager import FileManagementAgent
from app.agents.rate_limiter import RateLimitingAgent

from app.models.config import SystemConfig
from app.models.events import FileEvent, UploadRequest, EventType
from app.monitoring.tracing import trace_operation


class UploadOrchestratorAgent(BaseAgent):
    """Main orchestrator agent that coordinates the upload workflow"""
    
    agent_type: str = "orchestrator"
    config: SystemConfig = Field(...)
    file_watcher: Optional[FileWatcherAgent] = None
    image_analyzer: Optional[ImageAnalysisAgent] = None
    tumblr_publisher: Optional[TumblrPublishingAgent] = None
    file_manager: Optional[FileManagementAgent] = None
    rate_limiter: Optional[RateLimitingAgent] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        # Initialize base agent first
        super().__init__(**data)
        
        self._setup_agents()
    
    def _setup_agents(self):
        """Initialize all sub-agents"""
        try:
            # File watcher agent
            self.file_watcher = FileWatcherAgent(
                config=self.config.file_watcher,
                agent_id=f"{self.agent_id}_file_watcher"
            )
            
            # Image analysis agent
            self.image_analyzer = ImageAnalysisAgent(
                config=self.config.image_analysis,
                agent_id=f"{self.agent_id}_image_analyzer"
            )
            
            # Tumblr publisher agent
            self.tumblr_publisher = TumblrPublishingAgent(
                config=self.config.tumblr,
                agent_id=f"{self.agent_id}_tumblr_publisher"
            )
            
            # File manager agent
            self.file_manager = FileManagementAgent(
                config=self.config.file_management,
                agent_id=f"{self.agent_id}_file_manager"
            )
            
            # Rate limiter agent
            self.rate_limiter = RateLimitingAgent(
                config=self.config.rate_limit,
                agent_id=f"{self.agent_id}_rate_limiter"
            )
            
            self.logger.info("agents_initialized")
            
        except Exception as e:
            self.logger.error("agents_setup_error", error=str(e))
            raise
    
    async def _start_work(self):
        """Start the orchestrator and all sub-agents"""
        try:
            # Start all sub-agents
            await self._start_agents()
            
            # Start the main workflow
            asyncio.create_task(self._main_workflow())
            
            self.logger.info("orchestrator_started")
            
        except Exception as e:
            await self.handle_error(e, {"context": "start_work"})
            raise
    
    async def _stop_work(self):
        """Stop the orchestrator and all sub-agents"""
        await self._stop_agents()
        self.logger.info("orchestrator_stopped")
    
    async def _start_agents(self):
        """Start all sub-agents"""
        agents = [
            self.file_watcher,
            self.image_analyzer,
            self.tumblr_publisher,
            self.file_manager,
            self.rate_limiter
        ]
        
        for agent in agents:
            if agent:
                try:
                    await agent.start()
                    self.logger.info("agent_started", agent_type=agent.agent_type)
                except Exception as e:
                    self.logger.error("agent_start_error", 
                                    agent_type=agent.agent_type, 
                                    error=str(e))
                    raise
    
    async def _stop_agents(self):
        """Stop all sub-agents"""
        agents = [
            self.rate_limiter,
            self.file_manager,
            self.tumblr_publisher,
            self.image_analyzer,
            self.file_watcher
        ]
        
        for agent in agents:
            if agent:
                try:
                    await agent.stop()
                    self.logger.info("agent_stopped", agent_type=agent.agent_type)
                except Exception as e:
                    self.logger.error("agent_stop_error", 
                                    agent_type=agent.agent_type, 
                                    error=str(e))
    
    async def _main_workflow(self):
        """Main workflow loop that processes file events"""
        self.logger.info("main_workflow_started")
        
        # Scan for existing files first
        if self.file_watcher:
            await self.file_watcher.scan_existing_files()
        
        # Process file events as they come in
        if self.file_watcher:
            async for file_event in self.file_watcher.get_file_events():
                try:
                    await self.execute_task("process_upload_workflow", 
                                          self._process_upload_workflow, 
                                          file_event)
                except Exception as e:
                    await self.handle_error(e, {"file_event": str(file_event)})
    
    async def _process_upload_workflow(self, file_event: FileEvent):
        """Process a complete upload workflow for a file"""
        async with trace_operation(self.agent_id, "upload_workflow",
                                 metadata={"file_path": str(file_event.file_path),
                                          "category": file_event.category}) as span_id:
            
            self.logger.info("workflow_started",
                           file_path=str(file_event.file_path),
                           category=file_event.category)
            
            try:
                # Step 1: Check rate limits
                if not await self.rate_limiter.should_allow_upload():
                    self.logger.info("upload_rate_limited",
                                   file_path=str(file_event.file_path))
                    
                    # Wait for next available slot
                    wait_time = await self.rate_limiter.wait_for_next_slot()
                    self.logger.info("rate_limit_wait_completed",
                                   wait_time=wait_time)
                
                # Step 2: Create upload request
                upload_request = await self._create_upload_request(file_event)
                
                # Step 3: Analyze image if enabled
                if self.image_analyzer.is_analysis_enabled():
                    analysis = await self.image_analyzer.analyze_image(file_event.file_path)
                    
                    if analysis.description:
                        upload_request.caption = await self.image_analyzer.generate_caption(analysis)
                        
                        self.logger.info("image_analysis_completed",
                                       file_path=str(file_event.file_path),
                                       has_description=bool(analysis.description))
                    else:
                        self.logger.warning("image_analysis_failed",
                                          file_path=str(file_event.file_path),
                                          error=analysis.error)
                
                # Step 4: Upload to Tumblr
                upload_result = await self.tumblr_publisher.publish_post(upload_request)
                
                # Step 5: Record upload in rate limiter
                await self.rate_limiter.record_upload()
                
                # Step 6: Handle result
                if upload_result.success:
                    await self._handle_successful_upload(file_event, upload_result)
                else:
                    await self._handle_failed_upload(file_event, upload_result)
                
                self.logger.info("workflow_completed",
                               file_path=str(file_event.file_path),
                               success=upload_result.success,
                               post_id=upload_result.post_id)
                
            except Exception as e:
                await self._handle_workflow_error(file_event, e)
    
    async def _create_upload_request(self, file_event: FileEvent) -> UploadRequest:
        """Create an upload request from a file event"""
        # Build tags list
        tags = [file_event.category]
        if hasattr(self.config.tumblr, 'common_tags'):
            # Parse common tags from environment if available
            common_tags_str = getattr(self.config.tumblr, 'common_tags', '')
            if common_tags_str:
                common_tags = [tag.strip() for tag in common_tags_str.split(',') if tag.strip()]
                tags.extend(common_tags)
        
        return UploadRequest(
            file_path=file_event.file_path,
            category=file_event.category,
            tags=tags,
            state=self.config.tumblr.post_state.value,
            trace_id=file_event.trace_id
        )
    
    async def _handle_successful_upload(self, file_event: FileEvent, upload_result):
        """Handle successful upload"""
        # Clean up the file
        cleanup_success = await self.file_manager.cleanup_successful(file_event.file_path)
        
        if not cleanup_success:
            self.logger.warning("cleanup_failed_after_successful_upload",
                              file_path=str(file_event.file_path),
                              post_id=upload_result.post_id)
        
        # Emit success event
        self.emit_event(EventType.UPLOAD_COMPLETED, {
            "file_path": str(file_event.file_path),
            "category": file_event.category,
            "post_id": upload_result.post_id,
            "upload_time": upload_result.upload_time
        })
    
    async def _handle_failed_upload(self, file_event: FileEvent, upload_result):
        """Handle failed upload"""
        # Move file to failed directory
        move_success = await self.file_manager.move_to_failed(
            file_event.file_path,
            file_event.category,
            upload_result.error_message or "Unknown error"
        )
        
        if not move_success:
            self.logger.error("failed_to_move_failed_file",
                            file_path=str(file_event.file_path))
        
        # Emit failure event
        self.emit_event(EventType.UPLOAD_FAILED, {
            "file_path": str(file_event.file_path),
            "category": file_event.category,
            "error_message": upload_result.error_message,
            "error_type": upload_result.error_type
        })
    
    async def _handle_workflow_error(self, file_event: FileEvent, error: Exception):
        """Handle workflow errors"""
        self.logger.error("workflow_error",
                        file_path=str(file_event.file_path),
                        category=file_event.category,
                        error=str(error))
        
        # Move file to failed directory
        await self.file_manager.move_to_failed(
            file_event.file_path,
            file_event.category,
            f"Workflow error: {str(error)}"
        )
        
        await self.handle_error(error, {"file_event": str(file_event)})
    
    async def get_system_status(self) -> Dict[str, Any]:
        """Get comprehensive system status"""
        try:
            status = {
                "orchestrator": self.get_health_status().dict(),
                "agents": {},
                "rate_limits": {}
            }
            
            # Get agent statuses
            agents = {
                "file_watcher": self.file_watcher,
                "image_analyzer": self.image_analyzer,
                "tumblr_publisher": self.tumblr_publisher,
                "file_manager": self.file_manager,
                "rate_limiter": self.rate_limiter
            }
            
            for name, agent in agents.items():
                if agent:
                    status["agents"][name] = agent.get_health_status().dict()
            
            # Get rate limit status
            if self.rate_limiter:
                status["rate_limits"] = self.rate_limiter.get_rate_limit_status()
            
            # Get file manager stats
            if self.file_manager:
                status["storage"] = await self.file_manager.get_storage_stats()
            
            # Get queue sizes
            if self.file_watcher:
                status["queue_size"] = self.file_watcher.get_queue_size()
            
            return status
            
        except Exception as e:
            self.logger.error("system_status_error", error=str(e))
            return {"error": str(e)}
    
    async def validate_system(self) -> Dict[str, bool]:
        """Validate that all system components are working"""
        validation_results = {}
        
        try:
            # Test Tumblr connection with timeout
            self.logger.info("validation_step_starting", step="tumblr_connection")
            if self.tumblr_publisher:
                try:
                    validation_results["tumblr_connection"] = await asyncio.wait_for(
                        self.tumblr_publisher.test_connection(), 
                        timeout=10.0
                    )
                    self.logger.info("validation_step_completed", 
                                   step="tumblr_connection", 
                                   result=validation_results["tumblr_connection"])
                except asyncio.TimeoutError:
                    self.logger.warning("validation_step_timeout", step="tumblr_connection")
                    validation_results["tumblr_connection"] = False
                except Exception as e:
                    self.logger.error("validation_step_error", step="tumblr_connection", error=str(e))
                    validation_results["tumblr_connection"] = False
            else:
                validation_results["tumblr_connection"] = False
            
            # Test image analysis with timeout
            self.logger.info("validation_step_starting", step="image_analysis")
            if self.image_analyzer:
                try:
                    validation_results["image_analysis"] = await asyncio.wait_for(
                        self.image_analyzer.test_analysis(), 
                        timeout=10.0
                    )
                    self.logger.info("validation_step_completed", 
                                   step="image_analysis", 
                                   result=validation_results["image_analysis"])
                except asyncio.TimeoutError:
                    self.logger.warning("validation_step_timeout", step="image_analysis")
                    validation_results["image_analysis"] = False
                except Exception as e:
                    self.logger.error("validation_step_error", step="image_analysis", error=str(e))
                    validation_results["image_analysis"] = False
            else:
                validation_results["image_analysis"] = False
            
            # Test metrics system
            self.logger.info("validation_step_starting", step="metrics_working")
            validation_results["metrics_working"] = True
            try:
                if self.metrics:
                    # Test metrics by recording a test metric and retrieving system metrics
                    self.metrics.record_agent_error("test_agent", "test_error")
                    system_metrics = self.metrics.get_system_metrics()
                    validation_results["metrics_working"] = isinstance(system_metrics, dict)
                    self.logger.info("validation_step_completed", 
                                   step="metrics_working", 
                                   result=validation_results["metrics_working"])
                else:
                    validation_results["metrics_working"] = False
                    self.logger.info("validation_step_completed", 
                                   step="metrics_working", 
                                   result=False, 
                                   reason="no_metrics_instance")
            except Exception as e:
                self.logger.error("metrics_validation_error", error=str(e))
                validation_results["metrics_working"] = False
            
            # Check directory access and initialize directories
            self.logger.info("validation_step_starting", step="directories_accessible")
            validation_results["directories_accessible"] = True
            try:
                # Initialize directories and get discovered categories
                categories = self.config.initialize_directories()
                
                # Log discovered categories
                self.logger.info("categories_discovered", 
                               categories=categories,
                               auto_discover=self.config.file_watcher.auto_discover_categories)
                
                # Verify all category paths are accessible
                for category_path in self.config.get_category_paths().values():
                    if not category_path.exists():
                        validation_results["directories_accessible"] = False
                        break
                        
                self.logger.info("validation_step_completed", 
                               step="directories_accessible", 
                               result=validation_results["directories_accessible"])
            except Exception as e:
                self.logger.error("validation_step_error", step="directories_accessible", error=str(e))
                validation_results["directories_accessible"] = False
            
            self.logger.info("system_validation_completed", results=validation_results)
            
        except Exception as e:
            self.logger.error("system_validation_error", error=str(e))
            validation_results["validation_error"] = str(e)
        
        return validation_results 