# Multi-stage build for Tumblr Upload Agent System
FROM python:3.11-slim as builder

# Add container labels for GitHub Container Registry
LABEL org.opencontainers.image.source="https://github.com/jtenniswood/tumblr-agent"
LABEL org.opencontainers.image.description="Multi-agent system for automatically uploading images to Tumblr with AI-powered descriptions"
LABEL org.opencontainers.image.licenses="MIT"

# Set environment variables (rarely changes)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies for building (this layer rarely changes)
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment (this layer rarely changes)
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements first (separate from code for better caching)
COPY requirements.txt .

# Install Python dependencies (this layer only rebuilds when requirements.txt changes)
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r requirements.txt

# Production stage
FROM python:3.11-slim as production

# Set environment variables (rarely changes)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app"

# Install runtime dependencies (this layer rarely changes)
RUN apt-get update && apt-get install -y \
    procps \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Create non-root user (this layer rarely changes)
RUN groupadd -r tumblr && useradd -r -g tumblr tumblr

# Copy virtual environment from builder (only rebuilds if deps change)
COPY --from=builder /opt/venv /opt/venv

# Create application directory and data dirs (rarely changes)
WORKDIR /app
RUN mkdir -p /app/data/upload /app/data/failed && \
    chown -R tumblr:tumblr /app

# Copy only the application code (this changes most frequently)
# This way, code changes don't invalidate the expensive dependency layers above
COPY --chown=tumblr:tumblr app/ ./app/
COPY --chown=tumblr:tumblr requirements.txt .

# Switch to non-root user
USER tumblr

# Health check using process monitoring instead of HTTP
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD ps aux | grep -v grep | grep -q "python.*main.py" || exit 1

CMD ["python", "-m", "app.main"] 