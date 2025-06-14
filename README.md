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

## 🔑 Getting Started: Tumblr OAuth Setup

Before running the system, you need to obtain OAuth credentials from Tumblr to enable API access.

### Step 1: Create a Tumblr Application

1. **Go to the Tumblr OAuth Apps page:** https://www.tumblr.com/oauth/apps
2. **Login** to your Tumblr account
3. **Click** "Register application"
4. **Fill out the form:**
   - **Application name:** `Tumblr Upload Agent` (or any name you prefer)
   - **Application website:** `http://localhost:8080`
   - **Default callback URL:** `http://localhost:8080/oauth/callback` ⚠️ **Must be exact**
   - **Email:** Your email address
5. **Save** your **Consumer Key** and **Consumer Secret** - you'll need these in the next step

### Step 2: Generate OAuth Tokens

Use the [Tumblr OAuth Token Generator](https://github.com/jtenniswood/tumblr-oauth) to easily obtain your OAuth tokens:

1. **Run the OAuth token generator:**
   ```bash
   docker run -p 8080:5000 ghcr.io/jtenniswood/tumblr-oauth:latest
   ```

2. **Open** http://localhost:8080 in your browser

3. **Enter** your Consumer Key and Consumer Secret from Step 1

4. **Click** "Generate OAuth Tokens"

5. **Authorize** on Tumblr's website (opens automatically)

6. **Copy** your **OAuth Token** and **OAuth Token Secret**


## 🐳 Setting up using Docker Compose

1. **Copy and configure environment variables:**
   Download compose.yml and env.example from the docker folder.
   
   ```bash
   cp docker/env.example .env
   # Edit .env with your Tumblr and Gemini credentials and desired settings
   ```
2. **Start the system with Docker Compose:**
   ```bash
   docker compose up -d
   ```
   This is the preferred and easiest way to run the system.

