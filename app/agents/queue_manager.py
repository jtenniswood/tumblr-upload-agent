from pathlib import Path
from typing import List
from pydantic import Field
from app.agents.base import BaseAgent
from app.models.config import QueueManagerConfig, SystemConfig
import shutil

class QueueManagerAgent(BaseAgent):
    """Agent responsible for managing the upload queue size"""
    
    agent_type: str = "queue_manager"
    config: QueueManagerConfig = Field(...)

    async def _start_work(self):
        """Start the queue manager"""
        import asyncio
        self.running = True
        asyncio.create_task(self._monitor_queue())
        if hasattr(self, 'logger'):
            self.logger.info("queue_manager_started")

    async def _monitor_queue(self):
        """Monitor queue size and manage staging to upload transfers"""
        import asyncio
        while getattr(self, 'running', True):
            try:
                current_size = await self._get_current_queue_size()
                if current_size < self.config.min_queue_threshold:
                    await self._replenish_queue()
                await asyncio.sleep(self.config.check_interval)
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.error("queue_monitor_error", error=str(e))
                await asyncio.sleep(5.0)

    async def _replenish_queue(self):
        """Move files from staging to upload to reach target size"""
        current_size = await self._get_current_queue_size()
        needed = self.config.target_queue_size - current_size
        if needed <= 0:
            return
        categories = await self._get_staging_categories()
        if not categories:
            if hasattr(self, 'logger'):
                self.logger.info("no_staging_categories_available")
            return
        # Calculate distribution
        base_per_category = needed // len(categories)
        remainder = needed % len(categories)
        for i, category in enumerate(categories):
            images_to_move = base_per_category + (1 if i < remainder else 0)
            if images_to_move > 0:
                await self._move_category_images(category, images_to_move)

    async def _get_current_queue_size(self) -> int:
        """Return the current number of items in the upload queue (all categories)"""
        config = SystemConfig()
        total = 0
        for category, path in config.get_category_paths().items():
            if path.exists() and path.is_dir():
                total += sum(1 for f in path.iterdir() if f.is_file())
        return total

    async def _get_staging_categories(self) -> List[str]:
        """Return a list of category folders in the staging directory"""
        categories = []
        staging_dir = self.config.staging_dir
        if staging_dir.exists() and staging_dir.is_dir():
            for item in staging_dir.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    categories.append(item.name)
        return sorted(categories)

    async def _move_category_images(self, category: str, count: int):
        """Move up to 'count' images from the given category in staging to upload"""
        staging_dir = self.config.staging_dir / category
        config = SystemConfig()
        upload_paths = config.get_category_paths()
        upload_dir = upload_paths.get(category)
        if not upload_dir:
            # Create the upload category directory if it doesn't exist
            upload_dir = config.file_watcher.base_upload_folder / category
            upload_dir.mkdir(parents=True, exist_ok=True)
        if not staging_dir.exists() or not staging_dir.is_dir():
            return
        files = [f for f in staging_dir.iterdir() if f.is_file()]
        files_to_move = files[:count]
        for file_path in files_to_move:
            dest_path = upload_dir / file_path.name
            try:
                shutil.move(str(file_path), str(dest_path))
                if hasattr(self, 'logger'):
                    self.logger.info("file_moved_to_upload", file=str(file_path), dest=str(dest_path), category=category)
            except Exception as e:
                if hasattr(self, 'logger'):
                    self.logger.error("move_file_error", file=str(file_path), dest=str(dest_path), error=str(e)) 