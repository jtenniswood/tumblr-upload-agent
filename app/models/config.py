from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator
from typing import List, Optional, Dict, Union
from pathlib import Path
from enum import Enum

# Manually load .env file to ensure variables are available
from dotenv import load_dotenv
import os
load_dotenv()

# Explicitly set the problematic environment variable if it exists in the .env file
if not os.getenv('ENABLE_IMAGE_ANALYSIS'):
    # Try to read it directly from .env file
    try:
        with open('.env', 'r') as f:
            for line in f:
                if line.strip().startswith('ENABLE_IMAGE_ANALYSIS='):
                    value = line.split('=', 1)[1].strip()
                    os.environ['ENABLE_IMAGE_ANALYSIS'] = value
                    break
    except:
        pass


class PostState(str, Enum):
    PUBLISHED = "published"
    DRAFT = "draft"
    QUEUE = "queue"
    PRIVATE = "private"


class TumblrConfig(BaseSettings):
    """Tumblr API configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    consumer_key: str = Field(..., env="CONSUMER_KEY")
    consumer_secret: str = Field(..., env="CONSUMER_SECRET")
    oauth_token: str = Field(..., env="OAUTH_TOKEN")
    oauth_secret: str = Field(..., env="OAUTH_SECRET")
    blog_name: str = Field(..., env="BLOG_NAME")
    post_state: PostState = Field(PostState.PUBLISHED, env="POST_STATE")

    @field_validator('blog_name')
    @classmethod
    def validate_blog_name(cls, v):
        if not v:
            raise ValueError("Blog name is required")
        return v


class ImageAnalysisConfig(BaseSettings):
    """Image analysis configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    gemini_api_key: str = Field("", env="GEMINI_API_KEY")
    gemini_model: str = Field("gemini-1.5-flash", env="GEMINI_MODEL")
    description_append_text: str = Field("", env="DESCRIPTION_APPEND_TEXT")
    gemini_prompt: str = Field(
        "Describe this image in 1-2 concise sentences. "
        "Focus on the visual elements and describe what is in the image, "
        "not any text it contains. Keep it brief and clear. "
        "Do not state Here is a description of the image.",
        env="GEMINI_PROMPT"
    )

    @property
    def enable_analysis(self) -> bool:
        """Convert string to boolean by reading environment variable directly"""
        # Read directly from environment variable
        value = os.getenv('ENABLE_IMAGE_ANALYSIS', 'false')
        return value.lower() in ('true', '1', 'yes', 'on')


class FileWatcherConfig(BaseSettings):
    """File watcher configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    base_upload_folder: Path = Field(Path("./data/upload"), env="BASE_UPLOAD_FOLDER")
    categories: Optional[Union[List[str], str]] = Field(None, env="CATEGORIES")
    polling_interval: float = Field(1.0, env="POLLING_INTERVAL")
    file_extensions: Union[List[str], str] = Field([".jpg", ".jpeg", ".png", ".gif"], env="FILE_EXTENSIONS")
    auto_discover_categories: bool = Field(True, env="AUTO_DISCOVER_CATEGORIES")

    @field_validator('categories', mode='before')
    @classmethod
    def parse_categories(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            return [c.strip() for c in v.split(",") if c.strip()]
        return v

    @field_validator('file_extensions', mode='before')
    @classmethod
    def parse_extensions(cls, v):
        if isinstance(v, str):
            return [ext.strip() for ext in v.split(",") if ext.strip()]
        return v

    def get_categories(self) -> List[str]:
        """Get categories either from config or by auto-discovery"""
        if self.categories and not self.auto_discover_categories:
            # Use explicitly configured categories
            return self.categories
        
        # Auto-discover categories from subdirectories
        discovered_categories = []
        
        if self.base_upload_folder.exists():
            for item in self.base_upload_folder.iterdir():
                if item.is_dir() and not item.name.startswith('.'):
                    discovered_categories.append(item.name)
        
        # If no directories found and we have configured categories, use those as fallback
        if not discovered_categories and self.categories:
            return self.categories
        
        # Sort for consistent ordering
        return sorted(discovered_categories)

    def ensure_category_directories(self) -> List[str]:
        """Ensure category directories exist and return the list"""
        categories = self.get_categories()
        
        # Create base upload directory if it doesn't exist
        self.base_upload_folder.mkdir(parents=True, exist_ok=True)
        
        # Create category subdirectories
        for category in categories:
            category_path = self.base_upload_folder / category
            category_path.mkdir(parents=True, exist_ok=True)
        
        return categories


class FileManagementConfig(BaseSettings):
    """File management configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    failed_upload_base: Path = Field(Path("./data/failed"), env="FAILED_UPLOAD_BASE")
    cleanup_after_days: int = Field(30, env="CLEANUP_AFTER_DAYS")


class RateLimitConfig(BaseSettings):
    """Rate limiting configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    upload_delay: float = Field(5.0, env="UPLOAD_DELAY")
    max_uploads_per_hour: int = Field(100, env="MAX_UPLOADS_PER_HOUR")
    max_uploads_per_day: int = Field(1000, env="MAX_UPLOADS_PER_DAY")
    burst_limit: int = Field(5, env="BURST_LIMIT")


class MonitoringConfig(BaseSettings):
    """Monitoring configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    dashboard_port: int = Field(8080, env="DASHBOARD_PORT")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    enable_tracing: bool = Field(True, env="ENABLE_TRACING")
    health_check_interval: float = Field(30.0, env="HEALTH_CHECK_INTERVAL")
    human_readable_logs: bool = Field(True, env="HUMAN_READABLE_LOGS")


class OrchestratorConfig(BaseSettings):
    """Main orchestrator configuration"""
    model_config = SettingsConfigDict(extra="ignore")
    
    agent_id: str = Field("orchestrator", env="AGENT_ID")
    max_concurrent_uploads: int = Field(3, env="MAX_CONCURRENT_UPLOADS")
    retry_attempts: int = Field(3, env="RETRY_ATTEMPTS")
    retry_delay: float = Field(10.0, env="RETRY_DELAY")


class SystemConfig:
    """Complete system configuration"""
    
    def __init__(self):
        self.tumblr = TumblrConfig()
        self.image_analysis = ImageAnalysisConfig()
        self.file_watcher = FileWatcherConfig()
        self.file_management = FileManagementConfig()
        self.rate_limit = RateLimitConfig()
        self.monitoring = MonitoringConfig()
        self.orchestrator = OrchestratorConfig()

    def get_category_paths(self) -> Dict[str, Path]:
        """Get mapping of category names to their folder paths"""
        categories = self.file_watcher.get_categories()
        return {
            category: self.file_watcher.base_upload_folder / category
            for category in categories
        }

    def initialize_directories(self) -> List[str]:
        """Initialize all required directories and return discovered categories"""
        # Ensure category directories exist and get the final list
        categories = self.file_watcher.ensure_category_directories()
        
        # Create other required directories
        self.file_management.failed_upload_base.mkdir(parents=True, exist_ok=True)
        
        return categories 