import asyncio
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum
import aiohttp
import json
import structlog

from app.models.config import NotificationConfig


class AlertSeverity(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    EMERGENCY = "emergency"


@dataclass
class Alert:
    """Alert data structure"""
    title: str
    message: str
    severity: AlertSeverity = AlertSeverity.NORMAL
    tags: Optional[str] = None
    url: Optional[str] = None
    url_title: Optional[str] = None


class PushOverNotifier:
    """PushOver notification service"""
    
    def __init__(self, config: NotificationConfig):
        self.config = config
        self.logger = structlog.get_logger().bind(component="pushover_notifier")
        self.session: Optional[aiohttp.ClientSession] = None
        self.last_alert_time: Dict[str, float] = {}  # For rate limiting
        self.min_alert_interval = 300  # 5 minutes minimum between same alerts
        
    async def __aenter__(self):
        """Async context manager entry"""
        if not self.session:
            self.session = aiohttp.ClientSession()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
            self.session = None
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send an alert via PushOver"""
        if not self.config.enable_notifications:
            self.logger.info("notifications_disabled", alert_title=alert.title)
            return False
            
        if not self.config.is_pushover_configured:
            self.logger.warning("pushover_not_configured", alert_title=alert.title)
            return False
        
        # Rate limiting: prevent spam of the same alert
        alert_key = f"{alert.title}:{alert.message}"
        current_time = time.time()
        
        if alert_key in self.last_alert_time:
            time_since_last = current_time - self.last_alert_time[alert_key]
            if time_since_last < self.min_alert_interval:
                self.logger.info("alert_rate_limited", 
                               alert_title=alert.title,
                               time_since_last=time_since_last)
                return False
        
        try:
            # Build PushOver payload
            payload = {
                "token": self.config.pushover_api_token,
                "user": self.config.pushover_user_key,
                "title": alert.title,
                "message": alert.message,
                "priority": self._get_priority_value(alert.severity),
            }
            
            # Add optional fields
            if alert.tags:
                payload["tags"] = alert.tags
            if alert.url:
                payload["url"] = alert.url
            if alert.url_title:
                payload["url_title"] = alert.url_title
            
            # Ensure we have a session
            if not self.session:
                self.session = aiohttp.ClientSession()
                
            # Send the notification
            async with self.session.post(
                "https://api.pushover.net/1/messages.json",
                data=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response_data = await response.json()
                
                if response.status == 200 and response_data.get("status") == 1:
                    self.logger.info("alert_sent_successfully", 
                                   alert_title=alert.title,
                                   pushover_response=response_data)
                    
                    # Update rate limiting
                    self.last_alert_time[alert_key] = current_time
                    return True
                else:
                    self.logger.error("alert_send_failed",
                                    alert_title=alert.title,
                                    status_code=response.status,
                                    pushover_response=response_data)
                    return False
                    
        except Exception as e:
            self.logger.error("alert_send_exception",
                            alert_title=alert.title,
                            error=str(e),
                            error_type=type(e).__name__)
            return False
    
    def _get_priority_value(self, severity: AlertSeverity) -> int:
        """Convert severity to PushOver priority value"""
        priority_map = {
            AlertSeverity.LOW: -1,
            AlertSeverity.NORMAL: 0,
            AlertSeverity.HIGH: 1,
            AlertSeverity.EMERGENCY: 2
        }
        return priority_map.get(severity, 0)


class NotificationService:
    """Main notification service that manages different notification channels"""
    
    def __init__(self, config: NotificationConfig):
        self.config = config
        self.logger = structlog.get_logger().bind(component="notification_service")
        self.pushover = PushOverNotifier(config)
        
    async def send_gemini_api_error_alert(self, error_details: str) -> bool:
        """Send alert for Gemini API key errors"""
        alert = Alert(
            title="🚨 Gemini API Key Error",
            message=f"Image processing has been disabled due to invalid Gemini API key.\n\n"
                   f"Error details: {error_details}\n\n"
                   f"Please check your GEMINI_API_KEY configuration and restart the service.",
            severity=AlertSeverity.HIGH,
            tags="gemini,api,error"
        )
        
        async with self.pushover:
            return await self.pushover.send_alert(alert)
    
    async def send_system_alert(self, title: str, message: str, 
                               severity: AlertSeverity = AlertSeverity.NORMAL,
                               tags: Optional[str] = None) -> bool:
        """Send a generic system alert"""
        alert = Alert(
            title=title,
            message=message,
            severity=severity,
            tags=tags
        )
        
        async with self.pushover:
            return await self.pushover.send_alert(alert)
    
    async def test_notification(self) -> bool:
        """Test notification system"""
        alert = Alert(
            title="🧪 Test Notification",
            message="This is a test notification from the Tumblr Upload Agent System.",
            severity=AlertSeverity.LOW,
            tags="test"
        )
        
        async with self.pushover:
            return await self.pushover.send_alert(alert)


# Global notification service instance
_notification_service: Optional[NotificationService] = None


def get_notification_service(config: Optional[NotificationConfig] = None) -> NotificationService:
    """Get or create the notification service instance"""
    global _notification_service
    
    if _notification_service is None:
        if config is None:
            from app.models.config import SystemConfig
            config = SystemConfig().notifications
        _notification_service = NotificationService(config)
    
    return _notification_service


def reset_notification_service():
    """Reset the notification service (mainly for testing)"""
    global _notification_service
    _notification_service = None