# Tumblr Upload Agent System

A sophisticated multi-agent system for automatically uploading images to Tumblr with AI-powered descriptions and comprehensive monitoring.

## 🌟 Features

- **Multi-Agent Architecture**: File watcher, image analysis, image conversion, Tumblr publisher, file manager, rate limiter, and orchestrator agents
- **AI Image Analysis**: Automatic image description generation using Google Gemini AI
- **Smart Image Conversion**: Automatic conversion of AVIF, BMP, and TIFF files to JPG for Tumblr compatibility
- **Smart Rate Limiting**: Hourly, daily, and burst limits with automatic retry
- **Distributed Tracing**: Track requests across agents with structured logging
- **File Organization**: Automatic categorization and cleanup

## 📸 Supported Image Formats

### Native Tumblr Support
- **JPG/JPEG** - Uploaded directly
- **PNG** - Uploaded directly  
- **GIF** - Uploaded directly
- **WebP** - Uploaded directly

### Auto-Converted Formats
- **AVIF** - Converted to high-quality JPG
- **BMP** - Converted to high-quality JPG
- **TIFF/TIF** - Converted to high-quality JPG
- **Other unsupported formats** - The agent will attempt to convert any unsupported image type to JPG automatically.

The system automatically detects unsupported formats and converts them to JPG with configurable quality settings (default: 95%). Original files can optionally be preserved after conversion.

## 🐳 Docker Usage

### Recommended Setup (Docker Compose)

1. **Copy and configure environment variables:**
   ```bash
   cp docker/env.example .env
   # Edit .env with your Tumblr and Gemini credentials and desired settings
   ```
2. **Start the system with Docker Compose:**
   ```bash
   docker compose -f docker/compose.yml up -d
   ```
   This is the preferred and easiest way to run the system.

### Using Pre-built Images (Advanced)

You can also run the container directly, but Docker Compose is recommended for managing environment variables and volumes:

```bash
# Pull the latest image
docker pull ghcr.io/jtenniswood/tumblr-agent:latest

# Run directly (not recommended for most users)
docker run -d \
  --name tumblr-agent \
  -v $(pwd)/upload:/app/data/upload \
  -v $(pwd)/staging:/app/data/failed \
  --env-file .env \
  ghcr.io/jtenniswood/tumblr-agent:latest
```

### Available Tags

- `