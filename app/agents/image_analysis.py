import asyncio
import time
from pathlib import Path
from typing import Optional, Any
from pydantic import Field

from app.agents.base import BaseAgent
from app.models.config import ImageAnalysisConfig
from app.models.events import ImageAnalysis
from app.monitoring.tracing import trace_operation
from app.monitoring.notifications import get_notification_service


class ImageAnalysisAgent(BaseAgent):
    """Agent responsible for analyzing images and generating descriptions"""
    
    agent_type: str = "image_analysis"
    config: ImageAnalysisConfig = Field(...)
    gemini_model: Optional[Any] = None
    _api_key_invalid: bool = False
    _notification_service: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self._notification_service = get_notification_service()
        self._setup_gemini()
    
    def _setup_gemini(self):
        """Setup Gemini AI model if API key is available"""
        if not self.config.gemini_api_key or not self.config.enable_analysis:
            self.logger.info("gemini_disabled", 
                           has_api_key=bool(self.config.gemini_api_key),
                           analysis_enabled=self.config.enable_analysis)
            return
        
        try:
            import google.generativeai as genai
            
            genai.configure(api_key=self.config.gemini_api_key)
            self.gemini_model = genai.GenerativeModel(self.config.gemini_model)
            
            self.logger.info("gemini_initialized", model=self.config.gemini_model)
            
        except ImportError:
            self.logger.error("gemini_import_error", 
                            error="google-generativeai package not installed")
        except Exception as e:
            self.logger.error("gemini_setup_error", error=str(e))
    
    async def _start_work(self):
        """Start the image analysis agent"""
        # Test the API key if model is configured
        if self.gemini_model and not self._api_key_invalid:
            await self._test_api_key()
        
        self.logger.info("image_analysis_agent_started")
    
    async def _stop_work(self):
        """Stop the image analysis agent"""
        self.logger.info("image_analysis_agent_stopped")
    
    async def _test_api_key(self) -> bool:
        """Test the Gemini API key validity"""
        if not self.gemini_model:
            self.logger.error("gemini_api_test_failed", error="Gemini model not initialized")
            return False
            
        try:
            # Try to generate a simple test response
            response = self.gemini_model.generate_content(
                "Test message - respond with 'OK'",
                generation_config={"temperature": 0.1}
            )
            
            if response.text:
                self.logger.info("gemini_api_test_successful")
                return True
            else:
                raise Exception("Empty response from Gemini API")
                
        except Exception as e:
            error_msg = str(e)
            self.logger.error("gemini_api_test_failed", error=error_msg)
            
            # Check if it's an API key related error
            if self._is_api_key_error(error_msg):
                self._api_key_invalid = True
                self.logger.error("gemini_api_key_invalid", 
                                error="API key is invalid or expired")
                
                # Send alert via PushOver
                await self._send_api_key_alert(error_msg)
                return False
            
            # Other errors might be temporary
            return False
    
    def _is_api_key_error(self, error_msg: str) -> bool:
        """Check if the error is related to API key issues"""
        api_key_error_indicators = [
            "API key",
            "authentication",
            "unauthorized",
            "invalid key",
            "forbidden",
            "401",
            "403",
            "PERMISSION_DENIED",
            "UNAUTHENTICATED"
        ]
        
        error_lower = error_msg.lower()
        return any(indicator.lower() in error_lower for indicator in api_key_error_indicators)
    
    async def _send_api_key_alert(self, error_details: str):
        """Send alert for invalid API key"""
        try:
            await self._notification_service.send_gemini_api_error_alert(error_details)
            self.logger.info("api_key_alert_sent", error_details=error_details)
        except Exception as e:
            self.logger.error("failed_to_send_api_key_alert", 
                            error=str(e), 
                            original_error=error_details)
    
    async def analyze_image(self, file_path: Path) -> ImageAnalysis:
        """Analyze an image and return description"""
        return await self.execute_task("analyze_image", self._analyze_image_impl, file_path)
    
    async def _analyze_image_impl(self, file_path: Path) -> ImageAnalysis:
        """Implementation of image analysis"""
        async with trace_operation(self.agent_id, "analyze_image",
                                 metadata={"file_path": str(file_path)}) as span_id:
            
            start_time = time.time()
            
            # Check if API key is marked as invalid
            if self._api_key_invalid:
                return ImageAnalysis(
                    file_path=file_path,
                    description=None,
                    error="Image analysis disabled due to invalid Gemini API key",
                    analysis_time=time.time() - start_time
                )
            
            # Check if analysis is enabled and model is available
            if not self.config.enable_analysis or not self.gemini_model:
                return ImageAnalysis(
                    file_path=file_path,
                    description=None,
                    error="Image analysis disabled or not configured",
                    analysis_time=time.time() - start_time
                )
            
            # Validate file exists and is readable
            if not file_path.exists():
                return ImageAnalysis(
                    file_path=file_path,
                    description=None,
                    error="File does not exist",
                    analysis_time=time.time() - start_time
                )
            
            try:
                # Import PIL for image handling
                from PIL import Image
                
                # Open and validate image
                image = Image.open(file_path)
                
                # Generate description using Gemini with configurable prompt
                prompt = self.config.gemini_prompt
                
                response = self.gemini_model.generate_content(
                    [prompt, image],
                    generation_config={"temperature": 0.1}
                )
                
                description = response.text.strip() if response.text else None
                analysis_time = time.time() - start_time
                
                # Record metrics
                if self.metrics:
                    self.metrics.record_image_analysis(analysis_time)
                
                self.logger.info("image_analyzed",
                               file_path=str(file_path),
                               description_length=len(description) if description else 0,
                               analysis_time=analysis_time)
                
                return ImageAnalysis(
                    file_path=file_path,
                    description=description,
                    confidence=0.8,  # Placeholder confidence score
                    analysis_time=analysis_time
                )
                
            except ImportError as e:
                error_msg = f"PIL not available: {str(e)}"
                self.logger.error("pil_import_error", error=error_msg)
                return ImageAnalysis(
                    file_path=file_path,
                    description=None,
                    error=error_msg,
                    analysis_time=time.time() - start_time
                )
                
            except Exception as e:
                error_msg = f"Analysis failed: {str(e)}"
                self.logger.error("analysis_error",
                                file_path=str(file_path),
                                error=error_msg)
                
                # Check if this is an API key error during analysis
                if self._is_api_key_error(error_msg):
                    self._api_key_invalid = True
                    self.logger.error("gemini_api_key_invalid_during_analysis",
                                    error="API key became invalid during analysis")
                    
                    # Send alert
                    await self._send_api_key_alert(error_msg)
                    
                    return ImageAnalysis(
                        file_path=file_path,
                        description=None,
                        error="Image analysis disabled due to invalid Gemini API key",
                        analysis_time=time.time() - start_time
                    )
                
                await self.handle_error(e, {"file_path": str(file_path)})
                
                return ImageAnalysis(
                    file_path=file_path,
                    description=None,
                    error=error_msg,
                    analysis_time=time.time() - start_time
                )
    
    async def generate_caption(self, analysis: ImageAnalysis) -> str:
        """Generate a caption from image analysis (no template needed - using folder-based tags)"""
        return await self.execute_task("generate_caption", 
                                     self._generate_caption_impl, 
                                     analysis)
    
    async def _generate_caption_impl(self, analysis: ImageAnalysis) -> str:
        """Implementation of caption generation"""
        async with trace_operation(self.agent_id, "generate_caption",
                                 metadata={"has_description": bool(analysis.description)}) as span_id:
            
            # Start with the AI description
            caption = analysis.description or ""
            
            # Append custom text if configured
            if self.config.description_append_text:
                if caption:  # Only add separator if there's already content
                    caption += "\n\n\n"  # Extra paragraph break for better separation
                caption += self.config.description_append_text
            
            self.logger.info("caption_generated",
                           file_path=str(analysis.file_path),
                           caption_length=len(caption),
                           has_append_text=bool(self.config.description_append_text))
            
            return caption
    
    def is_analysis_enabled(self) -> bool:
        """Check if image analysis is enabled and configured"""
        return (self.config.enable_analysis and 
                bool(self.config.gemini_api_key) and 
                self.gemini_model is not None and
                not self._api_key_invalid)
    
    async def test_analysis(self) -> bool:
        """Test if image analysis is working"""
        if not self.is_analysis_enabled():
            return False
        
        return await self._test_api_key()
    
    def get_api_key_status(self) -> dict:
        """Get the current API key status"""
        return {
            "has_api_key": bool(self.config.gemini_api_key),
            "model_initialized": self.gemini_model is not None,
            "api_key_invalid": self._api_key_invalid,
            "analysis_enabled": self.config.enable_analysis,
            "can_analyze": self.is_analysis_enabled()
        } 