import asyncio
import time
from pathlib import Path
from typing import Optional, Dict, Any, ClassVar, Set
from PIL import Image
from pydantic import Field
import pillow_avif_plugin  # Ensure AVIF support is registered

from app.agents.base import BaseAgent
from app.models.config import ImageConversionConfig
from app.monitoring.tracing import trace_operation


class ImageConversionAgent(BaseAgent):
    """Agent responsible for converting unsupported image formats"""
    
    agent_type: str = "image_conversion"
    config: ImageConversionConfig = Field(...)
    
    # Formats that need conversion to JPG
    CONVERT_TO_JPG: ClassVar[Set[str]] = {'.avif', '.bmp', '.tiff', '.tif'}
    # Formats that are already supported by Tumblr
    SUPPORTED_FORMATS: ClassVar[Set[str]] = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
    
    async def _start_work(self):
        """Start the image conversion agent"""
        self.logger.info("image_conversion_agent_started")
    
    async def _stop_work(self):
        """Stop the image conversion agent"""
        self.logger.info("image_conversion_agent_stopped")
    
    async def convert_if_needed(self, file_path: Path) -> Optional[Path]:
        """Convert file if format is not supported, return new path or None"""
        return await self.execute_task("convert_if_needed", 
                                     self._convert_if_needed_impl, 
                                     file_path)
    
    async def _convert_if_needed_impl(self, file_path: Path) -> Optional[Path]:
        """Implementation of conditional conversion"""
        async with trace_operation(self.agent_id, "convert_if_needed",
                                 metadata={"file_path": str(file_path)}) as span_id:
            
            if not self.config.enable_conversion:
                return None
            
            file_ext = file_path.suffix.lower()
            
            if file_ext in self.SUPPORTED_FORMATS:
                self.logger.debug("format_already_supported",
                                file_path=str(file_path),
                                format=file_ext)
                return None  # No conversion needed
                
            if file_ext in self.CONVERT_TO_JPG:
                self.logger.info("conversion_needed",
                               file_path=str(file_path),
                               from_format=file_ext,
                               to_format=".jpg")
                return await self._convert_to_jpg(file_path)
                
            # Unsupported format entirely
            self.logger.warning("unsupported_format",
                              file_path=str(file_path),
                              format=file_ext)
            return None
    
    async def _convert_to_jpg(self, file_path: Path) -> Path:
        """Convert image to JPG format"""
        async with trace_operation(self.agent_id, "convert_to_jpg",
                                 metadata={"file_path": str(file_path)}) as span_id:
            
            start_time = time.time()
            
            # Generate output path
            output_path = file_path.with_suffix('.jpg')
            
            # Handle filename conflicts
            counter = 1
            while output_path.exists():
                stem = file_path.stem
                output_path = file_path.parent / f"{stem}_converted_{counter}.jpg"
                counter += 1
            
            try:
                # Run conversion in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._convert_image_sync, file_path, output_path)
                
                conversion_time = time.time() - start_time
                
                # Record metrics
                if self.metrics:
                    from_format = file_path.suffix.lower()
                    self.metrics.record_image_conversion(conversion_time, from_format)
                
                self.logger.info("image_converted",
                               source=str(file_path),
                               destination=str(output_path),
                               conversion_time=conversion_time,
                               quality=self.config.conversion_quality)
                
                return output_path
                
            except Exception as e:
                self.logger.error("conversion_failed",
                                file_path=str(file_path),
                                error=str(e))
                await self.handle_error(e, {"file_path": str(file_path)})
                raise
    
    def _convert_image_sync(self, input_path: Path, output_path: Path):
        """Synchronous image conversion"""
        try:
            with Image.open(input_path) as img:
                # Convert to RGB if needed (AVIF might be RGBA)
                if img.mode in ('RGBA', 'LA', 'P'):
                    # Create white background for transparency
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    if img.mode in ('RGBA', 'LA'):
                        background.paste(img, mask=img.split()[-1])
                    else:
                        background.paste(img)
                    img = background
                elif img.mode != 'RGB':
                    img = img.convert('RGB')
                
                # Save as JPG with configured quality
                img.save(output_path, 'JPEG', 
                        quality=self.config.conversion_quality, 
                        optimize=True)
                        
        except Exception as e:
            # Clean up partial file if it exists
            if output_path.exists():
                output_path.unlink()
            raise e
    
    def is_conversion_enabled(self) -> bool:
        """Check if image conversion is enabled"""
        return self.config.enable_conversion
    
    def needs_conversion(self, file_path: Path) -> bool:
        """Check if a file needs conversion"""
        if not self.config.enable_conversion:
            return False
        
        file_ext = file_path.suffix.lower()
        return file_ext in self.CONVERT_TO_JPG
    
    def get_supported_formats(self) -> set:
        """Get all supported formats (native + convertible)"""
        if self.config.enable_conversion:
            return self.SUPPORTED_FORMATS | self.CONVERT_TO_JPG
        return self.SUPPORTED_FORMATS 