import asyncio
import time
from pathlib import Path
from typing import List, Optional, Dict, Any
import requests
from requests_oauthlib import OAuth1
from datetime import datetime
from pydantic import Field

from app.agents.base import BaseAgent
from app.models.config import TumblrConfig
from app.models.events import UploadRequest, UploadResult
from app.monitoring.tracing import trace_operation


class TumblrAPI:
    """Tumblr API client with OAuth1 authentication"""
    
    def __init__(self, consumer_key: str, consumer_secret: str, 
                 oauth_token: str, oauth_secret: str):
        self.api_base = "https://api.tumblr.com/v2"
        self.auth = OAuth1(
            consumer_key,
            consumer_secret,
            oauth_token,
            oauth_secret
        )
    
    def create_photo_post(self, blog_name: str, file_path: Path, 
                         tags: List[str] = None, caption: str = "", 
                         state: str = "published") -> dict:
        """Create a photo post on Tumblr"""
        url = f"{self.api_base}/blog/{blog_name}/post"
        
        # Prepare the multipart form data
        data = {
            'type': 'photo',
            'state': state,
            'tags': ','.join(tags) if tags else '',
            'caption': caption or ''
        }
        
        # Prepare the file
        with open(file_path, 'rb') as f:
            files = {'data': f}
            response = requests.post(url, auth=self.auth, data=data, files=files)
        
        return response.json()
    
    def test_connection(self, blog_name: str) -> bool:
        """Test API connection and credentials"""
        try:
            url = f"{self.api_base}/blog/{blog_name}/info"
            response = requests.get(url, auth=self.auth, timeout=5.0)  # 5 second timeout
            return response.status_code == 200
        except Exception:
            return False


class TumblrPublishingAgent(BaseAgent):
    """Agent responsible for publishing posts to Tumblr"""
    
    agent_type: str = "tumblr_publisher"
    config: TumblrConfig = Field(...)
    tumblr_client: Optional[Any] = None
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, **data):
        super().__init__(**data)
        self._setup_tumblr_client()
    
    def _setup_tumblr_client(self):
        """Setup Tumblr API client"""
        try:
            self.tumblr_client = TumblrAPI(
                self.config.consumer_key,
                self.config.consumer_secret,
                self.config.oauth_token,
                self.config.oauth_secret
            )
            
            self.logger.info("tumblr_api_initialized", blog_name=self.config.blog_name)
            
        except Exception as e:
            self.logger.error("tumblr_api_setup_error", error=str(e))
    
    async def _start_work(self):
        """Start the Tumblr publishing agent"""
        # Test API connection
        if await self.test_connection():
            self.logger.info("tumblr_connection_verified")
        else:
            self.logger.warning("tumblr_connection_failed")
        
        self.logger.info("tumblr_publisher_started")
    
    async def _stop_work(self):
        """Stop the Tumblr publishing agent"""
        self.logger.info("tumblr_publisher_stopped")
    
    async def test_connection(self) -> bool:
        """Test connection to Tumblr API"""
        if not self.tumblr_client:
            return False
        
        try:
            # Run in thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                self.tumblr_client.test_connection, 
                self.config.blog_name
            )
            return result
        except Exception as e:
            self.logger.error("connection_test_error", error=str(e))
            return False
    
    async def publish_post(self, request: UploadRequest) -> UploadResult:
        """Publish a post to Tumblr"""
        return await self.execute_task("publish_post", self._publish_post_impl, request)
    
    async def _publish_post_impl(self, request: UploadRequest) -> UploadResult:
        """Implementation of post publishing"""
        async with trace_operation(self.agent_id, "publish_post",
                                 metadata={"file_path": str(request.file_path),
                                          "category": request.category,
                                          "state": request.state}) as span_id:
            
            start_time = time.time()
            
            # Validate API client is available
            if not self.tumblr_client:
                return UploadResult(
                    success=False,
                    error_message="Tumblr API client not initialized",
                    error_type="configuration_error",
                    upload_time=time.time() - start_time,
                    file_path=request.file_path,
                    category=request.category
                )
            
            # Validate file exists
            if not request.file_path.exists():
                return UploadResult(
                    success=False,
                    error_message="File does not exist",
                    error_type="file_error",
                    upload_time=time.time() - start_time,
                    file_path=request.file_path,
                    category=request.category
                )
            
            try:
                self.logger.info("upload_starting",
                               file_path=str(request.file_path),
                               category=request.category,
                               tags=request.tags)
                
                # Record upload attempt
                if self.metrics:
                    self.metrics.record_upload_attempt(request.category)
                
                # Run API call in thread pool to avoid blocking
                loop = asyncio.get_event_loop()
                response = await loop.run_in_executor(
                    None,
                    self.tumblr_client.create_photo_post,
                    self.config.blog_name,
                    request.file_path,
                    request.tags,
                    request.caption or "",
                    request.state
                )
                
                upload_time = time.time() - start_time
                
                # Check if upload was successful
                if response and 'response' in response and 'id' in response['response']:
                    post_id = str(response['response']['id'])
                    
                    # Record success metrics
                    if self.metrics:
                        self.metrics.record_upload_success(request.category, upload_time)
                    
                    self.logger.info("upload_successful",
                                   file_path=str(request.file_path),
                                   category=request.category,
                                   post_id=post_id,
                                   upload_time=upload_time)
                    
                    return UploadResult(
                        success=True,
                        post_id=post_id,
                        upload_time=upload_time,
                        file_path=request.file_path,
                        category=request.category
                    )
                else:
                    # Upload failed
                    error_message = self._extract_error_message(response)
                    error_type = self._classify_error(response)
                    
                    # Record failure metrics
                    if self.metrics:
                        self.metrics.record_upload_failure(request.category, error_type)
                    
                    self.logger.error("upload_failed",
                                    file_path=str(request.file_path),
                                    category=request.category,
                                    error_message=error_message,
                                    error_type=error_type,
                                    response=response)
                    
                    return UploadResult(
                        success=False,
                        error_message=error_message,
                        error_type=error_type,
                        upload_time=upload_time,
                        file_path=request.file_path,
                        category=request.category
                    )
                    
            except requests.exceptions.RequestException as e:
                upload_time = time.time() - start_time
                error_type = "network_error"
                error_message = f"Network error: {str(e)}"
                
                # Record failure metrics
                if self.metrics:
                    self.metrics.record_upload_failure(request.category, error_type)
                
                self.logger.error("upload_network_error",
                                file_path=str(request.file_path),
                                category=request.category,
                                error=str(e))
                
                await self.handle_error(e, {"file_path": str(request.file_path)})
                
                return UploadResult(
                    success=False,
                    error_message=error_message,
                    error_type=error_type,
                    upload_time=upload_time,
                    file_path=request.file_path,
                    category=request.category
                )
                
            except Exception as e:
                upload_time = time.time() - start_time
                error_type = "unknown_error"
                error_message = f"Unexpected error: {str(e)}"
                
                # Record failure metrics
                if self.metrics:
                    self.metrics.record_upload_failure(request.category, error_type)
                
                self.logger.error("upload_unexpected_error",
                                file_path=str(request.file_path),
                                category=request.category,
                                error=str(e))
                
                await self.handle_error(e, {"file_path": str(request.file_path)})
                
                return UploadResult(
                    success=False,
                    error_message=error_message,
                    error_type=error_type,
                    upload_time=upload_time,
                    file_path=request.file_path,
                    category=request.category
                )
    
    def _extract_error_message(self, response: dict) -> str:
        """Extract error message from Tumblr API response"""
        if not response:
            return "No response from API"
        
        if 'errors' in response:
            errors = response['errors']
            if isinstance(errors, list) and errors:
                return str(errors[0])
            elif isinstance(errors, dict):
                return str(errors)
        
        if 'meta' in response and 'msg' in response['meta']:
            return response['meta']['msg']
        
        return f"Unknown error: {response}"
    
    def _classify_error(self, response: dict) -> str:
        """Classify error type from Tumblr API response"""
        if not response:
            return "no_response"
        
        if 'meta' in response and 'status' in response['meta']:
            status = response['meta']['status']
            if status == 401:
                return "authentication_error"
            elif status == 403:
                return "permission_error"
            elif status == 429:
                return "rate_limit_error"
            elif status >= 500:
                return "server_error"
            elif status >= 400:
                return "client_error"
        
        return "api_error"
    
    async def validate_credentials(self) -> bool:
        """Validate Tumblr API credentials"""
        return await self.test_connection() 