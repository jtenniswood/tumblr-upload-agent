import asyncio
import shutil
from pathlib import Path
from typing import Dict, Any
from datetime import datetime, timedelta
from pydantic import Field

from app.agents.base import BaseAgent
from app.models.config import FileManagementConfig
from app.monitoring.tracing import trace_operation


class FileManagementAgent(BaseAgent):
    """Agent responsible for file organization, cleanup, and management"""
    
    agent_type: str = "file_management"
    config: FileManagementConfig = Field(...)
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
    
    async def _start_work(self):
        """Start the file management agent"""
        await self._setup_directories()
        
        # Start periodic cleanup task
        asyncio.create_task(self._periodic_cleanup())
        
        self.logger.info("file_manager_started")
    
    async def _stop_work(self):
        """Stop the file management agent"""
        self.logger.info("file_manager_stopped")
    
    async def _setup_directories(self):
        """Setup required directories"""
        try:
            # Create failed upload directory
            self.config.failed_upload_base.mkdir(parents=True, exist_ok=True)
            
            self.logger.info("directories_setup",
                           failed_base=str(self.config.failed_upload_base))
                           
        except Exception as e:
            await self.handle_error(e, {"context": "setup_directories"})
            raise
    
    async def move_to_failed(self, file_path: Path, category: str, reason: str) -> bool:
        """Move a file to the failed uploads directory"""
        return await self.execute_task("move_to_failed", 
                                     self._move_to_failed_impl, 
                                     file_path, category, reason)
    
    async def _move_to_failed_impl(self, file_path: Path, category: str, reason: str) -> bool:
        """Implementation of moving file to failed directory"""
        async with trace_operation(self.agent_id, "move_to_failed",
                                 metadata={"file_path": str(file_path), "category": category, "reason": reason}) as span_id:
            
            if not file_path.exists():
                self.logger.warning("file_not_found_for_move",
                                  file_path=str(file_path))
                return False
            
            try:
                # Create category subdirectory in failed uploads
                failed_category_dir = self.config.failed_upload_base / category
                failed_category_dir.mkdir(parents=True, exist_ok=True)
                
                # Generate unique filename if file already exists
                destination = failed_category_dir / file_path.name
                counter = 1
                while destination.exists():
                    stem = file_path.stem
                    suffix = file_path.suffix
                    destination = failed_category_dir / f"{stem}_{counter}{suffix}"
                    counter += 1
                
                # Move the file
                shutil.move(str(file_path), str(destination))
                
                self.logger.info("file_moved_to_failed",
                               source=str(file_path),
                               destination=str(destination),
                               category=category,
                               reason=reason)
                
                return True
                
            except Exception as e:
                self.logger.error("move_to_failed_error",
                                file_path=str(file_path),
                                category=category,
                                error=str(e))
                await self.handle_error(e, {"file_path": str(file_path), "category": category})
                return False
    
    async def cleanup_successful(self, file_path: Path) -> bool:
        """Handle cleanup of successfully processed file"""
        return await self.execute_task("cleanup_successful", 
                                     self._cleanup_successful_impl, 
                                     file_path)
    
    async def _cleanup_successful_impl(self, file_path: Path) -> bool:
        """Implementation of successful file cleanup"""
        async with trace_operation(self.agent_id, "cleanup_successful",
                                 metadata={"file_path": str(file_path)}) as span_id:
            
            if not file_path.exists():
                self.logger.warning("file_not_found_for_cleanup",
                                  file_path=str(file_path))
                return False
            
            try:
                # Delete the original file
                file_path.unlink()
                
                self.logger.info("file_cleaned_up",
                               file_path=str(file_path))
                
                return True
                
            except Exception as e:
                self.logger.error("cleanup_error",
                                file_path=str(file_path),
                                error=str(e))
                await self.handle_error(e, {"file_path": str(file_path)})
                return False
    
    async def _periodic_cleanup(self):
        """Periodic cleanup of old files"""
        while self.is_running:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self._cleanup_old_files()
            except Exception as e:
                self.logger.error("periodic_cleanup_error", error=str(e))
                await asyncio.sleep(3600)  # Continue trying
    
    async def _cleanup_old_files(self):
        """Clean up old files based on configuration"""
        if self.config.cleanup_after_days <= 0:
            return
        
        cutoff_date = datetime.now() - timedelta(days=self.config.cleanup_after_days)
        
        # Clean up failed uploads
        await self._cleanup_directory(self.config.failed_upload_base, cutoff_date)
    
    async def _cleanup_directory(self, directory: Path, cutoff_date: datetime):
        """Clean up files older than cutoff date in a directory"""
        try:
            cleaned_count = 0
            
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    # Check file modification time
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)
                    
                    if file_mtime < cutoff_date:
                        try:
                            file_path.unlink()
                            cleaned_count += 1
                            
                            self.logger.debug("old_file_cleaned",
                                            file_path=str(file_path),
                                            age_days=(datetime.now() - file_mtime).days)
                        except Exception as e:
                            self.logger.warning("cleanup_file_error",
                                              file_path=str(file_path),
                                              error=str(e))
            
            # Remove empty directories
            for dir_path in directory.rglob("*"):
                if dir_path.is_dir() and not any(dir_path.iterdir()):
                    try:
                        dir_path.rmdir()
                    except Exception:
                        pass  # Ignore errors removing directories
            
            if cleaned_count > 0:
                self.logger.info("cleanup_completed",
                               directory=str(directory),
                               files_cleaned=cleaned_count,
                               cutoff_days=self.config.cleanup_after_days)
                               
        except Exception as e:
            self.logger.error("cleanup_directory_error",
                            directory=str(directory),
                            error=str(e))
    
    async def get_storage_stats(self) -> dict:
        """Get storage statistics"""
        try:
            stats = {
                "failed_uploads": self._get_directory_stats(self.config.failed_upload_base)
            }
            
            return stats
            
        except Exception as e:
            self.logger.error("storage_stats_error", error=str(e))
            return {}
    
    def _get_directory_stats(self, directory: Path) -> dict:
        """Get statistics for a directory"""
        try:
            if not directory.exists():
                return {"exists": False, "file_count": 0, "total_size": 0}
            
            file_count = 0
            total_size = 0
            
            for file_path in directory.rglob("*"):
                if file_path.is_file():
                    file_count += 1
                    total_size += file_path.stat().st_size
            
            return {
                "exists": True,
                "file_count": file_count,
                "total_size": total_size,
                "total_size_mb": round(total_size / (1024 * 1024), 2)
            }
            
        except Exception as e:
            self.logger.error("directory_stats_error",
                            directory=str(directory),
                            error=str(e))
            return {"exists": False, "file_count": 0, "total_size": 0, "error": str(e)} 