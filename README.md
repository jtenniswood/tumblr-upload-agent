# Tumblr Upload Agent System

A sophisticated multi-agent system for automatically uploading images to Tumblr with AI-powered descriptions and comprehensive monitoring.

## 🌟 Features

- **Multi-Agent Architecture**: File watcher, image analysis, Tumblr publisher, file manager, rate limiter, and orchestrator agents
- **AI Image Analysis**: Automatic image description generation using Google Gemini AI
- **Smart Rate Limiting**: Hourly, daily, and burst limits with automatic retry
- **Distributed Tracing**: Track requests across agents with structured logging
- **File Organization**: Automatic categorization and cleanup

## 🐳 Docker Usage

### Using Pre-built Images

The application is automatically built and published to GitHub Container Registry. You can use the pre-built images:

```bash
# Pull the latest image
docker pull ghcr.io/jtenniswood/tumblr-agent:latest

# Run with docker-compose (recommended)
docker-compose -f docker/docker-compose.yml up -d

# Or run directly
docker run -d \
  --name tumblr-agent \
  -v $(pwd)/data:/app/data \
  -e TUMBLR_API_KEY=your_api_key \
  -e TUMBLR_API_SECRET=your_api_secret \
  -e TUMBLR_ACCESS_TOKEN=your_access_token \
  -e TUMBLR_ACCESS_SECRET=your_access_secret \
  -e GEMINI_API_KEY=your_gemini_key \
  ghcr.io/jtenniswood/tumblr-agent:latest
```

### Available Tags

- `latest` - Latest stable release from main branch
- `develop` - Latest development build
- `v*` - Specific version releases (e.g., `v1.0.0`)
- `main-<sha>` - Specific commit from main branch

### Building Locally

```bash
# Build the image
docker build -f docker/Dockerfile -t tumblr-agent .

# Run with docker-compose
docker-compose -f docker/docker-compose.yml up -d
```
