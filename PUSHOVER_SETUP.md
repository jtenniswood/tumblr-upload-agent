# PushOver Notifications Setup

The Tumblr Upload Agent System now supports PushOver notifications for critical alerts, particularly when the Gemini API key becomes invalid or expires.

## Why PushOver Notifications?

When the Gemini API key is invalid or expires, the system will:
- ⛔ **Stop processing images** to prevent failures
- 🚨 **Send you an immediate alert** via PushOver
- 📝 **Log the error details** for troubleshooting

## Setting Up PushOver

### 1. Create a PushOver Account
1. Go to [pushover.net](https://pushover.net/) and create an account
2. Install the PushOver app on your phone/device

### 2. Get Your User Key
1. Log into your PushOver dashboard
2. Your **User Key** is displayed at the top of the page
3. Copy this key - you'll need it for `PUSHOVER_USER_KEY`

### 3. Create an Application
1. Go to [pushover.net/apps/build](https://pushover.net/apps/build)
2. Create a new application with these details:
   - **Name**: `Tumblr Upload Agent` (or any name you prefer)
   - **Type**: `Application`
   - **Description**: `Notifications for Tumblr Upload Agent System`
   - **URL**: (optional)
   - **Icon**: (optional)
3. After creation, copy the **API Token/Key**
4. Use this for `PUSHOVER_API_TOKEN`

### 4. Configure Environment Variables

Add these lines to your `.env` file:

```bash
# PushOver Notifications
ENABLE_NOTIFICATIONS=true
PUSHOVER_USER_KEY=your_user_key_here
PUSHOVER_API_TOKEN=your_api_token_here
```

### 5. Test the Setup

You can test the notification system by running:

```bash
# This will send a test notification
python -c "
import asyncio
from app.models.config import SystemConfig
from app.monitoring.notifications import get_notification_service

async def test():
    config = SystemConfig()
    notifier = get_notification_service(config.notifications)
    success = await notifier.test_notification()
    print(f'Test notification sent: {success}')

asyncio.run(test())
"
```

## Alert Types

The system will send alerts for:

### 🚨 Gemini API Key Errors
- **When**: API key is invalid, expired, or authentication fails
- **Action**: Image processing is automatically disabled
- **Priority**: High
- **Rate Limited**: Max 1 alert per 5 minutes for the same error

### 📊 System Alerts
- **When**: Other critical system errors occur
- **Action**: Depends on the error type
- **Priority**: Normal to High
- **Rate Limited**: Max 1 alert per 5 minutes for the same error

## Rate Limiting

To prevent spam, the system limits alerts to:
- **Same alert**: Maximum once every 5 minutes
- **Different alerts**: No limit (important alerts get through)

## Troubleshooting

### No Notifications Received
1. Check that `ENABLE_NOTIFICATIONS=true` in your `.env` file
2. Verify your `PUSHOVER_USER_KEY` and `PUSHOVER_API_TOKEN` are correct
3. Check the system logs for notification errors:
   ```bash
   # Look for these log entries
   grep -E "(pushover|notification|alert)" your_log_file.log
   ```

### API Key Validation
The system tests the Gemini API key when starting:
- ✅ **Valid**: Image analysis works normally
- ❌ **Invalid**: Alert sent, image processing disabled
- ⚠️ **Temporary Error**: No alert sent, system retries later

## Disabling Notifications

To disable notifications, set:
```bash
ENABLE_NOTIFICATIONS=false
```

Image analysis will still stop if the API key is invalid, but no alerts will be sent.

## Security Note

- Never share your PushOver keys in public repositories
- Use environment variables or secure secret management
- Keep your `.env` file private and excluded from version control